"""Contexto de un partido: probabilidades oficiales, cuotas, opciones de apuesta y matriz de marcadores.

Probabilidad "oficial" de un partido (la que muestra el dashboard):
  - liga con modelo validado y cuotas -> ensamble Elo + Dixon-Coles + mercado (pesos 2016-2025)
  - liga con modelo y sin cuotas      -> ensamble Elo + Dixon-Coles
  - liga sin modelo pero con cuotas   -> mercado sin margen
Over/Under 2,5 sigue la misma lógica (Dixon-Coles calibrado, combinado con el mercado si hay cuotas O/U).
Todas las demás selecciones (doble oportunidad, otras líneas, ambos marcan, combinadas del mismo partido)
salen de la matriz de marcadores ajustada a esas probabilidades oficiales (footy.markets.combos).
"""

import pickle
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from footy import config
from footy.betting import pro
from footy.betting.devig import proportional
from footy.db import repository as repo
from footy.db.connection import connect
from footy.leagues import load_params
from footy.markets import combos
from footy.prediction import recalibration, tracking
from footy.prediction.predictor import LeaguePredictor
from footy.web.services.betting import paper_bet, pro_verdict
from footy.web.services.catalog import league_names
from footy.web.services.common import _f, _probs, data_through, public

PREDICTOR_TTL = 6 * 3600
CONTEXT_TTL = 600
DISPLAY_BOOKS = ("Bet365", "Pinnacle", "Betfair Exchange", "Betfair", "Market Avg")   # cuota que se muestra
REFERENCE_BOOKS = ("Pinnacle", "Betfair Exchange", "Market Avg", "Bet365")             # para quitar el margen
STALE_DAYS = 12
HORIZON_DAYS = 3          # el dashboard muestra partidos de hoy, mañana y pasado mañana
LOCAL_TZ = ZoneInfo("America/Santiago")
PREDICTOR_DIR = config.PROJECT_ROOT / "data" / "cache" / "predictors"

_predictors: dict[str, tuple[float, LeaguePredictor]] = {}
_contexts: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
_upcoming_cache: dict[int, tuple[float, list]] = {}
_upcoming_lock = threading.Lock()


# --- predictores por liga ---------------------------------------------------

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


# --- cuotas -----------------------------------------------------------------

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


# --- contexto ------------------------------------------------------------------

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
        ctx["recommendation"] = paper_bet(params[code], p_off, books) if ref_book else {
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
    if pro_opps and ref.startswith("m:"):
        _attach_drift(pro_opps, int(ref[2:]))
    for o in combos.options(M):
        bo = oo.get(o["key"])
        po = pro_opps.get(o["key"])
        if po:                       # 1X2 con Pinnacle: precio justo sharp y la mejor cuota entre casas
            options.append({**o, "fair": _f(po["fair_odds"], 2), "odds": _f(po["odds"], 2), "book": po["book"],
                            "estimated": False, "ev": _f(po["edge"]), "p_fair": _f(po["p_fair"]),
                            "verdict": pro_verdict(po)})
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
                "top_scores": top_scores(M), "options": options,
                "suggestions": [{**s, "fair": _f(1 / s["p"], 2)} for s in combos.suggestions(M)],
                "odds_1x2": {b: [round(float(x), 2) for x in v] for b, v in books.items() if b in DISPLAY_BOOKS},
                "_M": M})
    return ctx


def _attach_drift(pro_opps: dict, match_id: int) -> None:
    """Movimiento de la cuota de Pinnacle de cada selección desde nuestra primera captura (si hay dos o más)."""
    from footy.data import load_odds_drift

    d = load_odds_drift(connect(), [match_id], books=(pro.SHARP,))
    for r in d.itertuples(index=False):
        o = pro_opps.get(pro.KEYS.get(r.selection))
        if o is not None:
            o["drift"] = {"from": round(float(r.first), 3), "to": round(float(r.last), 3),
                          "pct": round(float(r.drift), 4), "n": int(r.n), "signal": pro.steam(float(r.drift))}


def _form(r: dict | None) -> dict | None:
    """Forma reciente que usa el ML (para mostrarla): puntos por partido últimos 5, goles a favor/en contra (10)."""
    if not r:
        return None
    return {k: (None if r.get(k) is None or np.isnan(r[k]) else round(float(r[k]), 2))
            for k in ("form_h", "form_a", "gf_h", "ga_h", "gf_a", "ga_a", "h2h_n", "h2h_pts")}


def top_scores(M: np.ndarray, n: int = 3) -> list:
    flat = np.argsort(M, axis=None)[::-1][:n]
    return [[f"{i}-{j}", _f(M[i, j])] for i, j in zip(*np.unravel_index(flat, M.shape))]


def _cached_context(ref: str, build) -> dict:
    hit = _contexts.get(ref)
    if hit and time.time() - hit[0] < CONTEXT_TTL:
        return hit[1]
    ctx = build()
    _contexts[ref] = (time.time(), ctx)
    return ctx


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


FORM_N = 5


def recent_form(conn, team_ids, n: int = FORM_N) -> dict[int, list[str]]:
    """Últimos `n` resultados terminados de cada equipo ("W" gana, "D" empata, "L" pierde), del más antiguo al más
    reciente. Una sola consulta para todos los equipos (ROW_NUMBER por equipo), en cualquier competición."""
    ids = sorted({int(t) for t in team_ids if t is not None})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""WITH t AS (
              SELECT home_team_id AS team, kickoff_utc, home_goals AS gf, away_goals AS ga FROM matches
              WHERE status = 'finished' AND home_goals IS NOT NULL AND home_team_id IN ({marks})
              UNION ALL
              SELECT away_team_id, kickoff_utc, away_goals, home_goals FROM matches
              WHERE status = 'finished' AND home_goals IS NOT NULL AND away_team_id IN ({marks}))
            SELECT team, gf, ga FROM (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY team ORDER BY kickoff_utc DESC) AS rn FROM t)
            WHERE rn <= ? ORDER BY team, kickoff_utc""", (*ids, *ids, n)).fetchall()
    out: dict[int, list[str]] = {}
    for team, gf, ga in rows:
        out.setdefault(team, []).append("W" if gf > ga else "D" if gf == ga else "L")
    return out


def _upcoming(days: int) -> list[dict]:
    conn = connect()
    now = datetime.now(timezone.utc)
    # Hasta el final del día `days - 1` desde hoy en hora local (hoy, mañana y pasado mañana con days=3).
    local_today = datetime.now(LOCAL_TZ).date()
    end = datetime.combine(local_today + timedelta(days=days), datetime.min.time(), LOCAL_TZ)
    hidden = [c for c, v in config.settings()["competitions"].items() if v.get("history_only")]
    where_hidden = f"AND c.code NOT IN ({','.join('?' * len(hidden))})" if hidden else ""
    ids = [r[0] for r in conn.execute(
        f"""SELECT m.id FROM matches m JOIN competitions c ON c.id = m.competition_id
            WHERE m.status = 'scheduled' AND m.kickoff_utc BETWEEN ? AND ?
              {where_hidden}
            ORDER BY m.kickoff_utc""", (repo.to_iso(now), repo.to_iso(end), *hidden))]
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
    # Forma reciente para los puntos G/E/P del detalle (partidos ya terminados: todos anteriores a estos).
    form = recent_form(conn, [t for c in out for t in (c.get("home_id"), c.get("away_id"))])
    for c in out:
        h, a = form.get(c.get("home_id")), form.get(c.get("away_id"))
        if h or a:
            c["recent"] = {"home": h or [], "away": a or []}
    return out
