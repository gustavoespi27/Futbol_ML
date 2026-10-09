"""Datos para el dashboard web. Todo sale de la base SQLite, de config/league_models.json y de las
predicciones walk-forward guardadas por los análisis (data/processed/{shots,screen}/wf_*.csv).

Probabilidad "oficial" de un partido (la que muestra el dashboard):
  - liga con modelo validado y cuotas -> ensamble Elo + Dixon-Coles + mercado (pesos 2016-2025)
  - liga con modelo y sin cuotas      -> ensamble Elo + Dixon-Coles
  - liga sin modelo pero con cuotas   -> mercado sin margen
Over/Under 2,5 sigue la misma lógica (Dixon-Coles calibrado, combinado con el mercado si hay cuotas O/U).
Todas las demás selecciones (doble oportunidad, otras líneas, ambos marcan, combinadas del mismo partido)
salen de la matriz de marcadores ajustada a esas probabilidades oficiales (footy.markets.combos).
"""

import json
import pickle
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from footy import config
from footy.betting import pro
from footy.betting.devig import proportional
from footy.db import repository as repo
from footy.db.connection import connect
from footy.evaluation import live
from footy.ingest.football_data import leagues as fd_leagues
from footy.leagues import load_params
from footy.markets import combos
from footy.prediction import recalibration, tracking
from footy.prediction.predictor import LeaguePredictor

PREDICTOR_TTL = 6 * 3600
CONTEXT_TTL = 600
DISPLAY_BOOKS = ("Bet365", "Pinnacle", "Betfair Exchange", "Betfair", "Market Avg")   # cuota que se muestra
REFERENCE_BOOKS = ("Pinnacle", "Betfair Exchange", "Market Avg", "Bet365")             # para quitar el margen
STALE_DAYS = 12
HORIZON_DAYS = 3          # el dashboard muestra partidos de hoy, mañana y pasado mañana
LOCAL_TZ = ZoneInfo("America/Santiago")

_predictors: dict[str, tuple[float, LeaguePredictor]] = {}
_contexts: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


# --- utilidades ----------------------------------------------------------

def league_names() -> dict[str, str]:
    cfg = fd_leagues()
    names = {c: v["name"] for c, v in {**cfg["main"], **cfg["extra"]}.items()}
    for code, c in config.settings()["competitions"].items():
        names.setdefault(code, c["name"])
    return names


COUNTRY_ES = {
    "England": "Inglaterra", "Scotland": "Escocia", "Germany": "Alemania", "Italy": "Italia", "Spain": "España",
    "France": "Francia", "Netherlands": "Países Bajos", "Belgium": "Bélgica", "Portugal": "Portugal",
    "Turkey": "Turquía", "Greece": "Grecia", "Austria": "Austria", "Denmark": "Dinamarca", "Finland": "Finlandia",
    "Ireland": "Irlanda", "Norway": "Noruega", "Poland": "Polonia", "Romania": "Rumania", "Russia": "Rusia",
    "Sweden": "Suecia", "Switzerland": "Suiza", "Argentina": "Argentina", "Brazil": "Brasil", "Chile": "Chile",
    "Mexico": "México", "USA": "Estados Unidos", "China": "China", "Japan": "Japón",
    "Europe": "Copas UEFA", "South America": "Copas CONMEBOL", "World": "Selecciones",
}
CONTINENT = {
    **dict.fromkeys(["England", "Scotland", "Germany", "Italy", "Spain", "France", "Netherlands", "Belgium",
                     "Portugal", "Turkey", "Greece", "Austria", "Denmark", "Finland", "Ireland", "Norway", "Poland",
                     "Romania", "Russia", "Sweden", "Switzerland", "Europe"], "Europa"),
    **dict.fromkeys(["Argentina", "Brazil", "Chile", "South America"], "Sudamérica"),
    **dict.fromkeys(["Mexico", "USA"], "Norteamérica"),
    **dict.fromkeys(["China", "Japan"], "Asia"),
    "World": "Selecciones",
}


def league_catalog() -> list[dict]:
    """Todas las competiciones con país y continente (en español) y sus partidos de los próximos días."""
    cfg, comps = fd_leagues(), config.settings()["competitions"]
    info = {c: {"country": v["country"], "type": "league"} for g in ("main", "extra") for c, v in cfg[g].items()}
    info.update({c: {"country": v.get("country"), "type": v["type"]} for c, v in comps.items()})
    counts: dict[str, int] = {}
    for m in upcoming():
        counts[m["league"]] = counts.get(m["league"], 0) + 1
    names = league_names()
    out = []
    for code, v in info.items():
        country = v["country"] or ""
        out.append({"code": code, "name": names.get(code, code), "country": COUNTRY_ES.get(country, country),
                    "continent": CONTINENT.get(country, "Otros"), "type": v["type"], "n": counts.get(code, 0)})
    return sorted(out, key=lambda r: (-r["n"], r["name"]))


PREDICTOR_DIR = config.PROJECT_ROOT / "data" / "cache" / "predictors"


def _data_signature() -> str:
    """Lo único que cambia un predictor: los partidos terminados y los parámetros de las ligas."""
    from footy.leagues import PARAMS_PATH

    n, last = connect().execute("SELECT COUNT(*), MAX(kickoff_utc) FROM matches WHERE status = 'finished'").fetchone()
    return f"{n}|{last}|{PARAMS_PATH.stat().st_mtime_ns}"


def predictor(code: str) -> LeaguePredictor:
    """Predictor por liga. Ajustarlo toma 1-3 s y hay ~40 ligas, así que se guarda en disco y se reutiliza mientras
    la base de datos no cambie (la tarea diaria lo deja recalculado); en memoria se reutiliza unas horas."""
    with _lock:
        hit = _predictors.get(code)
        if hit and time.time() - hit[0] < PREDICTOR_TTL:
            return hit[1]
        path = PREDICTOR_DIR / f"{code}.pkl"
        sig = _data_signature()
        p = None
        if path.exists():
            try:
                saved = pickle.loads(path.read_bytes())
                p = saved["predictor"] if saved.get("sig") == sig else None
            except Exception:  # noqa: BLE001 - archivo corrupto o de otra versión: se reajusta
                p = None
        if p is None:
            p = LeaguePredictor(code)
            p.df = None                        # el historial completo no hace falta para predecir (achica el archivo)
            PREDICTOR_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pickle.dumps({"sig": sig, "predictor": p}))
        _predictors[code] = (time.time(), p)
        return p


def clear_caches() -> None:
    _upcoming_cache.clear()
    _predictors.clear()
    _contexts.clear()
    live.live_frame.cache_clear()
    live.combo_backtest.cache_clear()


def _f(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def _probs(p) -> list[float] | None:
    return None if p is None else [round(float(v), 4) for v in p]


def data_through(conn=None) -> dict[str, str]:
    """Fecha del último partido terminado por competición (para avisar si los datos están atrasados)."""
    conn = conn or connect()
    return {r[0]: r[1] for r in conn.execute(
        """SELECT c.code, MAX(m.kickoff_utc) FROM matches m JOIN competitions c ON c.id = m.competition_id
           WHERE m.status = 'finished' GROUP BY c.code""")}


# --- resumen ---------------------------------------------------------------

def overview() -> dict:
    bt = backtest()
    trk = tracking_data()
    conn = connect()
    last_api = conn.execute("SELECT MAX(requested_at) FROM api_requests").fetchone()[0]
    log = config.PROJECT_ROOT / "logs" / "daily.log"
    last_run = (datetime.fromtimestamp(log.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if log.exists() else None)
    return {"backtest": bt["summary"], "confidence": bt["confidence"], "tracking": trk["summary"],
            "last_api_request": last_api, "last_daily_run": last_run,
            "n_leagues_model": len(load_params()), "model_version": tracking.MODEL_VERSION}


# --- contexto de un partido: probabilidades, cuotas y opciones ----------------------------

def _books_1x2(odds: dict) -> dict[str, np.ndarray]:
    return {b: np.array([d[s] for s in "HDA"]) for b, d in odds["1X2"].items()
            if all(s in d and d[s] > 1 for s in "HDA")}


def _first_book(books, ok) -> str | None:
    ordered = [b for b in DISPLAY_BOOKS if b in books] + sorted(b for b in books if b not in DISPLAY_BOOKS)
    return next((b for b in ordered if ok(books[b])), None)


def _market_over(odds: dict) -> float | None:
    ou = odds["OU"]
    for b in ("Pinnacle", "Bet365", *sorted(ou)):
        d = ou.get(b, {})
        o, u = d.get((2.5, "OVER")), d.get((2.5, "UNDER"))
        if o and u:
            return (1 / o) / (1 / o + 1 / u)
    return None


def _option_odds(odds: dict) -> dict[str, dict]:
    """Cuota de la casa para cada selección (la primera casa de DISPLAY_BOOKS que la ofrezca).
    La doble oportunidad se estima desde el 1X2 de la misma casa (marcada como estimada)."""
    out = {}
    b1 = _books_1x2(odds)
    book = _first_book(b1, lambda _: True)
    if book:
        h, d, a = b1[book]
        for k, v in zip("1X2", (h, d, a)):
            out[k] = {"price": round(float(v), 2), "book": book, "estimated": False}
        for k, (x, y) in {"1X": (h, d), "X2": (d, a), "12": (h, a)}.items():
            est = 1 / (1 / x + 1 / y)
            if est > 1.01:                     # en partidos muy desiguales la estimación no tiene sentido
                out[k] = {"price": round(est, 2), "book": book, "estimated": True}
    for line in (1.5, 2.5, 3.5):
        bk = _first_book(odds["OU"], lambda d: (line, "OVER") in d and (line, "UNDER") in d)
        if bk:
            for sel, key in (("OVER", f"O{line}"), ("UNDER", f"U{line}")):
                out[key] = {"price": round(odds["OU"][bk][(line, sel)], 2), "book": bk, "estimated": False}
    bk = _first_book(odds["BTTS"], lambda d: "YES" in d and "NO" in d)
    if bk:
        for sel, key in (("YES", "BTTS_Y"), ("NO", "BTTS_N")):
            out[key] = {"price": round(odds["BTTS"][bk][sel], 2), "book": bk, "estimated": False}
    return out


def _ml_row(match_id: int | None) -> dict | None:
    """Predicción del modelo de machine learning para un partido programado (None si no hay)."""
    if match_id is None:
        return None
    try:
        from footy.prediction import ml_predict

        df = ml_predict.upcoming()
    except Exception:  # noqa: BLE001 - sin modelos entrenados el dashboard sigue con Elo + Dixon-Coles
        return None
    if df.empty or match_id not in df.index:
        return None
    r = df.loc[match_id]
    return None if np.isnan(r.ml_H) else r.to_dict()


def _build_context(ref: str, code: str, home: str, away: str, kickoff: str | None, odds: dict,
                   home_id: int | None = None, away_id: int | None = None) -> dict:
    params, names = load_params(), league_names()
    mlr = _ml_row(int(ref[2:])) if ref.startswith("m:") else None
    books = _books_1x2(odds)
    ref_book = next((b for b in REFERENCE_BOOKS if b in books), None) or next(iter(books), None)
    p_mkt_over = _market_over(odds)
    ctx = {"ref": ref, "league": code, "league_name": names.get(code, code), "home": home, "away": away,
           "kickoff": kickoff, "market_book": ref_book, "home_id": home_id, "away_id": away_id}
    if code in params:
        pred = predictor(code)
        if home_id is None:
            home_id, away_id = pred.find_team(home).id, pred.find_team(away).id
            ctx["home_id"], ctx["away_id"] = home_id, away_id
        pr = pred.probabilities(home_id, away_id, books[ref_book] if ref_book else None)
        # Modelo propio: ML (historial de equipos) si hay predicción; si no, Elo + Dixon-Coles.
        # Con cuotas manda la combinación validada con el mercado (el ML recibe peso ~0 frente al mercado).
        p_model = np.array([mlr["ml_H"], mlr["ml_D"], mlr["ml_A"]]) if mlr else pr["p_model"]
        p_off = pr["p_final"] if ref_book else p_model
        p_off = recalibration.scale(p_off, recalibration.current_T())   # ajuste automático con resultados reales
        p_dc_over = float(combos.over_prob(pr["lam"], pr["mu"], pred.dc.rho)[0])
        if p_mkt_over is None and mlr:
            p_over = float(mlr["ml_over25"])
        else:
            p_over = float(combos.calibrate_over(np.array([p_dc_over]),
                                                 None if p_mkt_over is None else np.array([p_mkt_over]),
                                                 params[code].get("ou"))[0])
        M = combos.fit_matrix(pr["lam"], pr["mu"], pred.dc.rho, p_off, p_over,
                              p_btts=float(mlr["ml_btts"]) if mlr else None)
        ctx.update({"source": "modelo + mercado" if ref_book else ("ML" if mlr else "modelo"),
                    "p_model": _probs(p_model), "model_name": "ML historial" if mlr else "Elo + Dixon-Coles",
                    "form": _form(mlr),
                    "p_market": _probs(pr.get("p_market")), "xg": [_f(pr["lam"], 2), _f(pr["mu"], 2)]})
        ctx["recommendation"] = _paper_bet(params[code], p_off, books) if ref_book else {
            "bet": False, "text": "Sin cuotas: no se puede evaluar valor."}
    elif ref_book:
        p_off = proportional(books[ref_book][None, :])[0]
        lam, mu = combos.implied_goals(p_off, p_mkt_over)
        M = combos.fit_matrix(lam, mu, 0.0, p_off, p_mkt_over)
        if mlr:
            ctx.update({"p_model": _probs([mlr["ml_H"], mlr["ml_D"], mlr["ml_A"]]), "model_name": "ML historial",
                        "form": _form(mlr)})
        ctx.update({"source": "mercado", "p_market": _probs(p_off), "xg": [_f(lam, 2), _f(mu, 2)],
                    "recommendation": {"bet": False, "text": "Sin modelo validado en esta liga: se muestra la "
                                                              "probabilidad del mercado."}})
    else:
        ctx.update({"source": "sin datos", "p_official": None, "options": [], "suggestions": [],
                    "recommendation": {"bet": False, "text": "Sin modelo validado ni cuotas todavía."}})
        return ctx
    oo = _option_odds(odds)
    options = []
    from footy.betting.suggestions import verdict

    pro_opps = {o["key"]: o for o in pro.evaluate(odds["1X2"])}
    for o in combos.options(M):
        bo = oo.get(o["key"])
        po = pro_opps.get(o["key"])
        if po:                       # 1X2 con Pinnacle: precio justo sharp y la mejor cuota entre casas
            options.append({**o, "fair": _f(po["fair_odds"], 2), "odds": _f(po["odds"], 2), "book": po["book"],
                            "estimated": False, "ev": _f(po["edge"]), "p_fair": _f(po["p_fair"]),
                            "verdict": _pro_verdict(po)})
            continue
        v = verdict(o["p"], bo["price"] if bo else None, bo["estimated"] if bo else False)
        if v["level"] == "green":    # sin referencia sharp el valor del modelo no está validado: nunca "Apostar"
            v = {"level": "yellow", "label": "Neutral",
                 "reason": "Valor según el modelo, sin referencia de Pinnacle (no validado)"}
        options.append({**o, "fair": _f(1 / o["p"], 2) if o["p"] > 0 else None,
                        "odds": bo["price"] if bo else None, "book": bo["book"] if bo else None,
                        "estimated": bo["estimated"] if bo else False,
                        "ev": _f(o["p"] * bo["price"] - 1) if bo else None, "verdict": v})
    ctx.update({"pro": list(pro_opps.values()), "has_sharp": bool(pro_opps),
                "p_official": _probs([combos.prob(M, [k]) for k in "1X2"]),
                "over25": _f(combos.prob(M, ["O2.5"])), "btts": _f(combos.prob(M, ["BTTS_Y"])),
                "top_scores": _top_scores(M), "options": options,
                "suggestions": [{**s, "fair": _f(1 / s["p"], 2)} for s in combos.suggestions(M)],
                "odds_1x2": {b: [round(float(x), 2) for x in v] for b, v in books.items() if b in DISPLAY_BOOKS},
                "_M": M})
    return ctx


def _form(r: dict | None) -> dict | None:
    """Forma reciente que usa el ML (para mostrarla): puntos por partido últimos 5, goles a favor/en contra (10)."""
    if not r:
        return None
    return {k: (None if r.get(k) is None or np.isnan(r[k]) else round(float(r[k]), 2))
            for k in ("form_h", "form_a", "gf_h", "ga_h", "gf_a", "ga_a", "h2h_n", "h2h_pts")}



def _pro_verdict(po: dict) -> dict:
    """Semáforo del apostador profesional para 1X2 (precio justo de Pinnacle vs la mejor cuota disponible)."""
    e = f"{po['edge'] * 100:+.1f}%".replace(".", ",")
    green = lambda r: {"level": "green", "label": "Apostar", "reason": r}  # noqa: E731
    red = lambda r: {"level": "red", "label": "No apostar", "reason": r}  # noqa: E731
    yellow = lambda r: {"level": "yellow", "label": "Neutral", "reason": r}  # noqa: E731
    if po["bet"]:
        return green(f"{po['book']} paga {e} sobre el precio justo de Pinnacle")
    if po["p_fair"] < 0.25 and po["edge"] < pro.MIN_EDGE:
        return red(f"Probabilidad baja ({po['p_fair']:.0%}) y sin valor ({e})")
    if po["edge"] >= pro.MIN_EDGE:
        return yellow(f"Valor {e} pero cuota > {pro.MAX_ODDS:g}: riesgo alto")
    if po["edge"] < -0.05:
        return red(f"La mejor cuota paga {e} respecto del precio justo")
    return yellow(f"Cerca del precio justo ({e}); falta ≥ +6%")


def _top_scores(M: np.ndarray, n: int = 3) -> list:
    flat = np.argsort(M, axis=None)[::-1][:n]
    return [[f"{i}-{j}", _f(M[i, j])] for i, j in zip(*np.unravel_index(flat, M.shape))]


def _paper_bet(params: dict, p, books: dict) -> dict:
    """Regla de seguimiento: EV > umbral de validación y cuota <= max_odds. Es seguimiento en papel, no consejo."""
    best = None
    for book, odds in books.items():
        ev = np.where(odds > params.get("max_odds", np.inf), -np.inf, np.asarray(p) * odds - 1)
        k = int(np.argmax(ev))
        if ev[k] > params["min_ev"] and (best is None or ev[k] > best["ev"]):
            best = {"bet": True, "sel": k, "book": book, "odds": _f(odds[k], 2), "ev": _f(ev[k])}
    if best:
        best["text"] = "Valor marginal según el modelo (solo seguimiento en papel; sin ventaja demostrada)."
        return best
    return {"bet": False, "text": "No apostar: ninguna cuota supera el umbral de valor."}


def _cached_context(ref: str, build) -> dict:
    hit = _contexts.get(ref)
    if hit and time.time() - hit[0] < CONTEXT_TTL:
        return hit[1]
    ctx = build()
    _contexts[ref] = (time.time(), ctx)
    return ctx


def public(ctx: dict) -> dict:
    return {k: v for k, v in ctx.items() if not k.startswith("_")}


def match_context(conn, match_id: int) -> dict:
    def build():
        r = conn.execute(
            """SELECT m.id, c.code, m.kickoff_utc, m.home_team_id, m.away_team_id, th.name AS home, ta.name AS away
               FROM matches m JOIN competitions c ON c.id = m.competition_id
               JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id WHERE m.id = ?""",
            (match_id,)).fetchone()
        if r is None:
            raise KeyError(f"Partido {match_id} no encontrado")
        return _build_context(f"m:{match_id}", r["code"], r["home"], r["away"], r["kickoff_utc"],
                              tracking.latest_market_odds(conn, match_id), r["home_team_id"], r["away_team_id"])
    return _cached_context(f"m:{match_id}", build)


def sim_context(code: str, home: str, away: str, odds: list[float] | None) -> dict:
    ref = f"s:{code}|{home}|{away}|{','.join(map(str, odds or []))}"
    user_odds = {"1X2": {"Tu casa": dict(zip("HDA", odds))} if odds else {}, "OU": {}, "BTTS": {}}
    return _cached_context(ref, lambda: _build_context(ref, code, home, away, None, user_odds))


def context(ref: str) -> dict:
    if ref.startswith("m:"):
        return match_context(connect(), int(ref[2:]))
    if ref.startswith("s:"):
        code, home, away, odds = ref[2:].split("|")
        return sim_context(code, home, away, [float(x) for x in odds.split(",")] if odds else None)
    raise KeyError(f"Referencia inválida: {ref}")


# --- próximos partidos -----------------------------------------------------

_upcoming_cache: dict[int, tuple[float, list]] = {}
_upcoming_lock = threading.Lock()


def upcoming(days: int = HORIZON_DAYS) -> list[dict]:
    """Partidos próximos con sus probabilidades. Se calcula una sola vez cada 5 minutos: las consultas simultáneas
    esperan el mismo resultado en vez de recalcularlo en paralelo (en frío tarda ~1 minuto)."""
    with _upcoming_lock:
        hit = _upcoming_cache.get(days)
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        out = _upcoming(days)
        _upcoming_cache[days] = (time.time(), out)
        return out


def _upcoming(days: int) -> list[dict]:
    conn = connect()
    now = datetime.now(timezone.utc)
    # Hasta el final del día `days - 1` desde hoy en hora local (hoy, mañana y pasado mañana con days=3).
    local_today = datetime.now(LOCAL_TZ).date()
    end = datetime.combine(local_today + timedelta(days=days), datetime.min.time(), LOCAL_TZ)
    ids = [r[0] for r in conn.execute(
        """SELECT m.id FROM matches m WHERE m.status = 'scheduled' AND m.kickoff_utc BETWEEN ? AND ?
           ORDER BY m.kickoff_utc""", (repo.to_iso(now), repo.to_iso(end)))]
    through = data_through(conn)
    out = []
    for mid in ids:
        try:
            ctx = public(match_context(conn, mid))
        except Exception as e:                       # un equipo sin historial no debe romper la página
            r = conn.execute("""SELECT c.code, m.kickoff_utc, th.name, ta.name FROM matches m
                                JOIN competitions c ON c.id = m.competition_id JOIN teams th ON th.id = m.home_team_id
                                JOIN teams ta ON ta.id = m.away_team_id WHERE m.id = ?""", (mid,)).fetchone()
            ctx = {"ref": f"m:{mid}", "league": r[0], "league_name": league_names().get(r[0], r[0]),
                   "kickoff": r[1], "home": r[2], "away": r[3], "source": "error", "error": str(e),
                   "options": [], "suggestions": [], "recommendation": {"bet": False, "text": str(e)}}
        last = through.get(ctx["league"])
        ctx["data_through"] = last
        ctx["stale"] = bool(last and (now - repo.from_iso(last)).days > STALE_DAYS)
        out.append(ctx)
    return out


# --- combinadas ---------------------------------------------------------------

def combo(legs: list[dict], group_odds: dict | None = None) -> dict:
    """legs: [{"ref", "key", "odds"?}]. Selecciones del mismo partido se evalúan juntas (probabilidad conjunta
    exacta); partidos distintos se multiplican. group_odds: cuota que ofrece la casa para una variante de un
    mismo partido ({ref: cuota}), porque las casas no la calculan como producto."""
    group_odds = group_odds or {}
    by_ref: dict[str, list[dict]] = {}
    for leg in legs:
        if leg["key"] not in combos.SELECTIONS:
            raise KeyError(f"Selección desconocida: {leg['key']}")
        by_ref.setdefault(leg["ref"], []).append(leg)
    groups, p_total, book_total, fair_total = [], 1.0, 1.0, 1.0
    for ref, gl in by_ref.items():
        ctx = context(ref)
        if "_M" not in ctx:
            raise KeyError(f"{ctx['home']} vs {ctx['away']}: sin probabilidades disponibles")
        keys = list(dict.fromkeys(leg["key"] for leg in gl))
        p = combos.prob(ctx["_M"], keys)
        opt = {o["key"]: o for o in ctx["options"]}
        if len(keys) == 1:
            user = gl[0].get("odds")
            book = user or opt[keys[0]]["odds"]
            book_src = "tuya" if user else opt[keys[0]]["book"]
        else:
            book = group_odds.get(ref)
            book_src = "tuya" if book else None
        groups.append({"ref": ref, "match": f"{ctx['home']} vs {ctx['away']}", "league_name": ctx["league_name"],
                       "league": ctx["league"], "home_id": ctx.get("home_id"), "away_id": ctx.get("away_id"),
                       "kickoff": ctx.get("kickoff"), "keys": keys, "label": combos.label(keys), "p": _f(p),
                       "fair": _f(1 / p, 2) if p > 0 else None, "odds": _f(book, 2), "odds_source": book_src,
                       "impossible": p == 0, "same_match": len(keys) > 1,
                       "items": [{"key": k, "label": combos.SELECTIONS[k][0], "p": _f(combos.prob(ctx["_M"], [k])),
                                  "odds": opt[k]["odds"], "book": opt[k]["book"]} for k in keys]})
        p_total *= p
        fair_total = fair_total * (1 / p) if p > 0 else None
        book_total = book_total * book if (book_total is not None and book) else None
    n = len(groups)
    hist = next((r for r in live.combo_backtest()["strategies"]["probables"] if r["legs"] == n), None) if n else None
    return {"groups": groups, "legs": n, "p": _f(p_total), "fair_odds": _f(fair_total, 2) if fair_total else None,
            "book_odds": _f(book_total, 2) if (n and book_total) else None,
            "ev": _f(p_total * book_total - 1) if (n and book_total) else None, "history": hist}


def ml_report() -> dict:
    path = config.path("processed") / "ml" / "report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def combo_history() -> dict:
    return live.combo_backtest()


# --- apuestas sugeridas -------------------------------------------------------

def _candidates(matches: list[dict]) -> list[dict]:
    now = repo.utc_now()
    out = []
    for m in matches:
        if not m.get("options") or not m["ref"].startswith("m:") or (m.get("kickoff") or "") <= now:
            continue
        for o in m["options"]:
            if o.get("odds"):
                out.append({"match": int(m["ref"][2:]), "ref": m["ref"], "key": o["key"], "label": o["label"],
                            "p": o["p"], "odds": float(o["odds"]), "book": o["book"], "estimated": o["estimated"],
                            "fair": o["fair"], "verdict": o.get("verdict"), "home": m["home"], "away": m["away"],
                            "home_id": m.get("home_id"), "away_id": m.get("away_id"), "league": m["league"],
                            "league_name": m["league_name"],
                            "kickoff": m["kickoff"], "source": m["source"]})
    return out


def current_suggestions(matches: list[dict] | None = None) -> dict:
    """Apuestas del apostador profesional (footy.betting.pro) para los próximos partidos."""
    from footy.betting import suggestions as sg

    matches = matches if matches is not None else upcoming()
    now = repo.utc_now()
    info = {m["ref"]: m for m in matches if m["ref"].startswith("m:") and (m.get("kickoff") or "") > now}
    opps = {int(ref[2:]): m.get("pro") or [] for ref, m in info.items()}
    labels = {"1": "Gana local", "X": "Empate", "2": "Gana visita"}
    enrich = lambda o: {**o, "p": o["p_fair"], "ev": o["edge"], "label": labels[o["key"]],  # noqa: E731
                        "ref": f"m:{o['match']}", **{k: info[f"m:{o['match']}"][k]
                                                     for k in ("home", "away", "league_name", "kickoff",
                                                               "home_id", "away_id", "league")}}
    singles = [{**s, "reason": pro.reason(s)} for s in (enrich(o) for o in pro.pick(opps))]
    near = [enrich({**o, "match": mid}) for mid, os_ in opps.items() for o in os_ if not o["bet"]
            and o["odds"] <= pro.MAX_ODDS and o["p_fair"] >= 0.25]
    closest_pro: dict = {}
    for c in sorted(near, key=lambda c: -c["edge"]):
        closest_pro.setdefault(c["match"], {**c, "verdict": _pro_verdict(c),
                                            "min_odds": round((1 + pro.MIN_EDGE) / c["p_fair"], 2)})
    cands = _candidates(matches)
    safest: dict = {}
    for c in cands:                                   # alta probabilidad (aunque el valor sea negativo)
        if not c["estimated"] and c["p"] >= 0.70 and c["odds"] >= 1.15:
            if c["match"] not in safest or c["p"] > safest[c["match"]]["p"]:
                safest[c["match"]] = {**c, "ev": c["p"] * c["odds"] - 1}
    doubles = sg.pick_doubles([{**s, "p": s["p_fair"]} for s in singles])
    for d in doubles:                    # en una doble el valor se multiplica pierna a pierna
        d["ev"] = float(np.prod([1 + leg["edge"] for leg in d["legs"]]) - 1)
        d["stake"] = min(pro.stake(d["p"], d["odds"]), pro.MAX_STAKE / 2)
    return {"rules": pro.RULES, "singles": singles, "doubles": doubles,
            "closest": list(closest_pro.values())[:6],
            "safest": sorted(safest.values(), key=lambda c: -c["p"])[:8],
            "n_matches_with_odds": len({c["match"] for c in cands}),
            "n_matches_sharp": sum(bool(v) for v in opps.values())}


def suggestions_data() -> dict:
    from footy.prediction import pro_ledger

    path = config.path("processed") / "pro" / "backtest.json"
    bt = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {**current_suggestions(), "history": live.combo_backtest().get("suggestions", {}),
            "pro_backtest": bt, "ledger": pro_ledger.record(connect())}


def reliable_data() -> dict:
    """Pronósticos fiables de hoy, su historial de aciertos y el ajuste automático de probabilidades."""
    from footy.prediction import reliable

    return {"today": reliable.candidates(upcoming())[:30], "record": reliable.record(connect()),
            "calibration": recalibration.load(), "min_p": reliable.MIN_P}


def register_reliable(conn=None) -> dict:
    from footy.prediction import reliable

    return reliable.register(conn or connect(), reliable.candidates(upcoming()))


def register_suggestions(conn=None) -> dict:
    """El apostador profesional coloca (en papel) sus apuestas antes del partido. Lo llama scripts/daily.py."""
    from footy.prediction import pro_ledger

    return pro_ledger.place(conn or connect(), current_suggestions()["singles"])


# --- seguimiento -----------------------------------------------------------

def tracking_data() -> dict:
    conn = connect()
    matches, bets = tracking.evaluate(conn, tracking.ALL_VERSIONS)
    pending = conn.execute(
        """SELECT COUNT(DISTINCT p.match_id) FROM predictions p JOIN matches m ON m.id = p.match_id
           WHERE m.status != 'finished'""").fetchone()[0]
    names = league_names()
    summary = {"evaluated": len(matches), "pending": pending, "paper_bets": len(bets)}
    rows = []
    if not matches.empty:
        matches = matches.sort_values("kickoff", ascending=False)
        mk = matches.ll_market_close.dropna()
        summary.update({"hit_rate": _f(matches.hit.mean()), "ll_official": _f(matches.ll_final.mean()),
                        "ll_model": _f(matches.ll_model.mean()),
                        "ll_market": _f(mk.mean()) if len(mk) else None, "n_market": len(mk),
                        "ll_official_same": _f(matches.loc[mk.index, "ll_final"].mean()) if len(mk) else None})
        for r in matches.to_dict("records"):
            rows.append({"kickoff": r["kickoff"], "league": r["league"], "league_name": names.get(r["league"]),
                         "home": r["home"], "away": r["away"], "home_id": r["home_id"], "away_id": r["away_id"],
                         "score": r["score"], "y": int(r["y"]),
                         "pick": r["pick"], "hit": bool(r["hit"]), "p_official": _probs(r["p_official"]),
                         "p_market": _probs(r["p_market"]), "version": r["model_version"],
                         "close_kind": r["close_kind"]})
    bet_rows = []
    if not bets.empty:
        summary.update({"bets_profit": _f(bets.profit.sum(), 2), "bets_yield": _f(bets.profit.mean()),
                        "bets_clv": _f(bets.clv.dropna().mean()) if bets.clv.notna().any() else None})
        for b in bets.sort_values("kickoff", ascending=False).to_dict("records"):
            bet_rows.append({"kickoff": b["kickoff"], "partido": b["partido"], "league": b["league"],
                             "book": b["book"], "sel": b["sel"], "odds": b["odds"], "ev": _f(b["ev"]),
                             "won": bool(b["won"]), "profit": _f(b["profit"], 2), "clv": _f(b["clv"]),
                             "version": b["model_version"]})
    return {"summary": summary, "matches": rows, "bets": bet_rows}


# --- backtest fuera de muestra (temporada 2026) --------------------------------

def _ll(P, y):
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], 1e-12, 1))))


def _ll_bin(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def backtest() -> dict:
    """Predicciones walk-forward de 2026: pesos y calibraciones ajustados con 2016-2025, así que es fuera de muestra."""
    params, names = load_params(), league_names()
    df = live.live_frame()
    y = df.y.to_numpy().astype(int)
    P = {k: df[[f"{k}_H", f"{k}_D", f"{k}_A"]].to_numpy() for k in ("mo", "of", "mk")}
    acc = {k: float((v.argmax(1) == y).mean()) for k, v in P.items()}
    lls = {k: _ll(v, y) for k, v in P.items()}
    summary = {"n": len(df), "leagues": int(df.code.nunique()), "from": df.kickoff_utc.min()[:10],
               "to": df.kickoff_utc.max()[:10],
               "acc_model": acc["mo"], "acc_market": acc["mk"], "acc_official": acc["of"],
               "ll_model": lls["mo"], "ll_market": lls["mk"], "ll_official": lls["of"],
               "acc_naive_home": float((y == 0).mean())}
    ou = df.dropna(subset=["p_over"])
    yo = (ou.home_goals + ou.away_goals > 2.5).to_numpy(float)
    summary["ou"] = {"n": len(ou), "over_rate": _f(yo.mean()),
                     **{f"acc_{k}": _f(((ou[c] > .5) == yo).mean()) for k, c in
                        (("model", "over_dc"), ("official", "over_off"), ("market", "p_over"))},
                     **{f"ll_{k}": _f(_ll_bin(ou[c].to_numpy(), yo)) for k, c in
                        (("model", "over_dc"), ("official", "over_off"), ("market", "p_over"))}}

    per_league = []
    for code, g in df.groupby("code"):
        yy = g.y.to_numpy().astype(int)
        Q = {k: g[[f"{k}_H", f"{k}_D", f"{k}_A"]].to_numpy() for k in ("mo", "of", "mk")}
        per_league.append({"code": code, "name": names.get(code, code), "n": len(g),
                           "acc_model": (Q["mo"].argmax(1) == yy).mean(),
                           "acc_market": (Q["mk"].argmax(1) == yy).mean(),
                           "acc_official": (Q["of"].argmax(1) == yy).mean(),
                           "ll_model": _ll(Q["mo"], yy), "ll_market": _ll(Q["mk"], yy), "ll_official": _ll(Q["of"], yy),
                           "status": params[code]["status"], "w_blend": params[code]["w_blend"]})
    per_league = [{k: (_f(v) if isinstance(v, (float, np.floating)) else v) for k, v in r.items()} for r in per_league]

    conf, top = [], P["of"].max(1)
    for lo, hi in ((0, .40), (.40, .50), (.50, .60), (.60, .70), (.70, 1.01)):
        m = (top >= lo) & (top < hi)
        if m.sum():
            conf.append({"range": f"{int(lo * 100)}–{min(int(hi * 100), 100)}%", "n": int(m.sum()),
                         "pred": _f(top[m].mean()), "hit": _f((P["of"][m].argmax(1) == y[m]).mean())})

    calib, onehot = {}, np.eye(3)[y]
    for k, lab in (("of", "official"), ("mo", "model")):
        p, o = P[k].ravel(), onehot.ravel()
        bins = np.minimum((p * 10).astype(int), 9)
        calib[lab] = [{"pred": _f(p[bins == b].mean()), "obs": _f(o[bins == b].mean()), "n": int((bins == b).sum())}
                      for b in range(10) if (bins == b).sum() >= 30]

    return {"summary": summary, "per_league": sorted(per_league, key=lambda r: r["name"]),
            "confidence": conf, "calibration": calib, "betting": _betting(df, P, y)}


def _betting(df: pd.DataFrame, P: dict, y: np.ndarray) -> dict:
    """Simulación a cuota de cierre de Bet365, 1 unidad por apuesta, en orden cronológico."""
    O = df[["b365_H", "b365_D", "b365_A"]].to_numpy()  # noqa: E741 - matriz de cuotas (convención del proyecto)
    min_ev, max_odds = df.min_ev.to_numpy(), df.max_odds.to_numpy()
    dates = df.kickoff_utc.str[:10].to_numpy()

    def run(Pr, cap: bool):
        ev = Pr * O - 1
        if cap:
            ev = np.where(O > max_odds[:, None], -np.inf, ev)
        ev = np.where(np.isnan(ev), -np.inf, ev)
        k = ev.argmax(1)
        e, o = ev[np.arange(len(y)), k], O[np.arange(len(y)), k]
        sel = e > min_ev
        profit = np.where(k[sel] == y[sel], o[sel] - 1, -1.0)
        curve = np.cumsum(profit)
        step = max(1, len(curve) // 150)
        n = len(profit)
        buckets = []
        for lo, hi in ((1, 2), (2, 3), (3, 4), (4, 6), (6, 1000)):
            m = (o[sel] > lo) & (o[sel] <= hi)
            if m.sum():
                buckets.append({"range": f"{lo}–{hi}" if hi < 1000 else f">{lo}", "n": int(m.sum()),
                                "yield": _f(profit[m].mean())})
        return {"n": n, "hit": _f((k[sel] == y[sel]).mean()) if n else None, "yield": _f(profit.mean()) if n else None,
                "ci": live._ci(profit), "profit": _f(profit.sum(), 1), "avg_odds": _f(o[sel].mean(), 2) if n else None,
                "curve": [{"d": dates[sel][i], "u": round(float(curve[i]), 1)} for i in range(0, n, step)]
                + ([{"d": dates[sel][-1], "u": round(float(curve[-1]), 1)}] if n else []),
                "buckets": buckets}

    return {"model_only": run(P["mo"], cap=False), "official_v2": run(P["of"], cap=True), "book": "Bet365 (cierre)"}


# --- ligas y simulador -------------------------------------------------------

def leagues_list() -> list[dict]:
    params, names = load_params(), league_names()
    bt = {r["code"]: r for r in backtest()["per_league"]}
    through = data_through()
    return [{"code": c, "name": names.get(c, c), "status": p["status"], "min_ev": p["min_ev"],
             "max_odds": p.get("max_odds"), "w_blend": p["w_blend"], "w_models": p["w_models"],
             "data_through": through.get(c), "live": bt.get(c)}
            for c, p in sorted(params.items(), key=lambda kv: names.get(kv[0], kv[0]))]


def teams(code: str) -> list[str]:
    p = predictor(code)
    active = set(p.recent_counts.index)
    return sorted(n for i, n in p.teams.items() if i in active)


def predict(code: str, home: str, away: str, odds: list[float] | None) -> dict:
    p = predictor(code)
    h, a = p.find_team(home), p.find_team(away)
    r = p.predict(h, a, tuple(odds) if odds else None)
    m = r["markets"]
    full = sim_context(code, h.name, a.name, odds)
    ctx = public(full)
    out = {"league": code, "league_name": r["league_name"], "home": h.name, "away": a.name,
           "home_id": h.id, "away_id": a.id,
           "p_model": _probs(r["p_model"]), "p_elo": _probs(r["p_elo"]), "p_dc": _probs(r["p_dc"]),
           "xg": [_f(m["xg_home"], 2), _f(m["xg_away"], 2)], "confidence": r["confidence"], "status": r["status"],
           "source": ctx["source"], "p_official": ctx["p_official"], "btts": ctx["btts"],
           "over_under": {o["key"][1:]: o["p"] for o in ctx["options"] if o["key"].startswith("O")},
           "top_scores": _top_scores(full["_M"], 5),
           "options": ctx["options"], "suggestions": ctx["suggestions"], "ref": ctx["ref"]}
    if odds:
        b = r["betting"]
        out["betting"] = {"odds": list(odds), "margin": _f(b["margin"]), "p_market": _probs(b["p_market_fair"]),
                          "ev": _probs(np.array(ctx["p_official"]) * np.array(odds) - 1), "min_ev": b["min_ev"]}
        out["recommendation"] = _paper_bet(p.params, np.array(ctx["p_official"]),
                                           {"Tu casa": np.array(odds, dtype=float)})
    return out


def to_json(obj):
    """json.dumps tolerante a tipos numpy."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
