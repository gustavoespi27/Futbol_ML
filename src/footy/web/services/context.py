"""Contexto de un partido: probabilidades oficiales, cuotas, opciones de apuesta y matriz de marcadores.

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
HORIZON_DAYS = 2          # hoy y mañana: el plan gratuito de API-Football no entrega calendario más allá
LOCAL_TZ = ZoneInfo("America/Santiago")
PREDICTOR_DIR = config.PROJECT_ROOT / "data" / "cache" / "predictors"

_predictors: dict[str, tuple[float, LeaguePredictor]] = {}
_contexts: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
_upcoming_cache: dict[int, tuple[float, list]] = {}
_upcoming_lock = threading.Lock()


_cross: dict[str, tuple[float, object]] = {}


def _cross_probs(code: str, home_id: int | None, away_id: int | None) -> np.ndarray | None:
    """P(1X2) del modelo entre ligas para una copa de clubes (None si no aplica o no está entrenado). Se recarga si
    la tarea diaria lo reentrenó."""
    from footy.models import cross_league

    if code not in cross_league.CUPS or home_id is None or away_id is None or not cross_league.PATH.exists():
        return None
    mtime = cross_league.PATH.stat().st_mtime
    hit = _cross.get("model")
    if hit is None or hit[0] != mtime:
        _cross["model"] = hit = (mtime, cross_league.load())
    return hit[1].probabilities(int(home_id), int(away_id))


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

def _upcoming_row(match_id: int | None) -> dict | None:
    """Fila de ml_predict.upcoming() de un partido programado: predicción ML y estadísticas previas (None si no hay)."""
    if match_id is None:
        return None
    try:
        from footy.prediction import ml_predict

        df = ml_predict.upcoming()
    except Exception:  # noqa: BLE001 - sin modelos entrenados el dashboard sigue con Elo + Dixon-Coles
        return None
    if df.empty or match_id not in df.index:
        return None
    return df.loc[match_id].to_dict()


# Estadísticas previas de cada equipo que se muestran (nombre en la API -> variable del historial).
STAT_KEYS = {"pts5": "pts_5", "gf10": "gf_10", "ga10": "ga_10", "sot10": "sf_10", "sot_against10": "sa_10",
             "shots10": "tf_10", "venue_pts5": "venue_pts5", "season_ppg": "season_ppg", "season_gd": "season_gd",
             "season_n": "season_n", "rest": "rest", "unbeaten": "unbeaten", "winless": "winless"}


def recent_h2h_matches(conn, home_id: int, away_id: int, before_kickoff: str, limit: int = 5) -> list[dict]:
    """Últimos enfrentamientos entre ambos clubes, en cualquier competición y condición. Anti-filtración: solo partidos
    terminados con marcador y con inicio estrictamente anterior a `before_kickoff`. `outcome` es desde la perspectiva
    del local del partido actual: W ganó, D empate, L ganó el rival de hoy."""
    names = league_names()
    rows = conn.execute(
        """SELECT m.kickoff_utc, c.code, m.home_team_id, m.away_team_id, th.name AS home, ta.name AS away,
                  m.home_goals, m.away_goals
           FROM matches m JOIN competitions c ON c.id = m.competition_id
           JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id
           WHERE m.status = 'finished' AND m.home_goals IS NOT NULL AND m.kickoff_utc < ?
             AND ((m.home_team_id = ? AND m.away_team_id = ?) OR (m.home_team_id = ? AND m.away_team_id = ?))
           ORDER BY m.kickoff_utc DESC LIMIT ?""",
        (before_kickoff, home_id, away_id, away_id, home_id, limit)).fetchall()
    out = []
    for r in rows:
        diff = r["home_goals"] - r["away_goals"]
        if r["home_team_id"] != home_id:                 # el local de hoy jugó de visita en ese partido
            diff = -diff
        out.append({"date": r["kickoff_utc"], "league": r["code"], "league_name": names.get(r["code"], r["code"]),
                    "home": r["home"], "away": r["away"], "home_id": r["home_team_id"], "away_id": r["away_team_id"],
                    "score": [r["home_goals"], r["away_goals"]],
                    "outcome": "W" if diff > 0 else "D" if diff == 0 else "L"})
    return out


def _stats(r: dict | None, conn=None, home_id: int | None = None, away_id: int | None = None,
           kickoff: str | None = None) -> dict | None:
    """Estadísticas previas (solo partidos ya jugados antes de este): forma, goles, tiros, temporada, descanso,
    rachas y enfrentamientos directos (con la lista de los últimos partidos entre ambos si se pasan ids y kickoff)."""
    if not r or "st_h_pts_5" not in r:
        return None

    def v(k):
        x = r.get(k)
        return None if x is None or np.isnan(x) else round(float(x), 2)

    out = {side: {k: v(f"st_{p}_{f}") for k, f in STAT_KEYS.items()} for side, p in (("home", "h"), ("away", "a"))}
    out["h2h"] = {"n": int(v("st_h2h_n") or 0), "pts": v("st_h2h_pts"), "gd": v("st_h2h_gd")}
    if conn is not None and home_id is not None and away_id is not None and kickoff:
        out["h2h"]["matches"] = recent_h2h_matches(conn, int(home_id), int(away_id), kickoff)
    return out


def _build_context(ref: str, code: str, home: str, away: str, kickoff: str | None, odds: dict,
                   home_id: int | None = None, away_id: int | None = None,
                   cross_probs: np.ndarray | None = None) -> dict:
    """`cross_probs`: probabilidades del modelo entre ligas ya calculadas (simulador entre ligas): se usan aunque la
    liga de `code` tenga modelo propio."""
    params, names = load_params(), league_names()
    row = _upcoming_row(int(ref[2:])) if ref.startswith("m:") else None
    mlr = None if row is None or np.isnan(row.get("ml_H", np.nan)) else row
    stats = _stats(row, connect(), home_id, away_id, kickoff) if row else None
    books = _books_1x2(odds)
    ref_book = next((b for b in REFERENCE_BOOKS if b in books), None) or next(iter(books), None)
    p_mkt_over = _market_over(odds)
    ctx = {"ref": ref, "league": code, "league_name": names.get(code, code), "home": home, "away": away,
           "kickoff": kickoff, "market_book": ref_book, "home_id": home_id, "away_id": away_id}
    cross = None
    if cross_probs is None and code in params:
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
        if stats:                                  # fuerza Elo de cada equipo (escala del predictor de la liga)
            for side, tid in (("home", home_id), ("away", away_id)):
                stats[side]["elo"] = round(float(pred.ratings[tid])) if tid in pred.ratings else None
        ctx.update({"source": "modelo + mercado" if ref_book else ("ML" if mlr else "modelo"),
                    "p_model": _probs(p_model), "model_name": "ML historial" if mlr else "Elo + Dixon-Coles",
                    "stats": stats,
                    "p_market": _probs(pr.get("p_market")), "xg": [_f(pr["lam"], 2), _f(pr["mu"], 2)]})
        ctx["recommendation"] = paper_bet(params[code], p_off, books) if ref_book else {
            "bet": False, "text": "Sin cuotas: no se puede evaluar valor."}
    elif ref_book or (cross := cross_probs if cross_probs is not None
                      else _cross_probs(code, home_id, away_id)) is not None:
        # Copas de clubes: modelo entre ligas (Elo global + ajuste por liga). Con cuotas manda Pinnacle sin margen
        # (no hay pesos validados para combinarlos) y el modelo se muestra al lado; sin cuotas, manda el modelo.
        p_off = proportional(books[ref_book][None, :])[0] if ref_book else cross
        lam, mu = combos.implied_goals(p_off, p_mkt_over)
        M = combos.fit_matrix(lam, mu, 0.0, p_off, p_mkt_over)
        if cross is not None:
            ctx.update({"p_model": _probs(cross), "model_name": "Elo entre ligas"})
        elif mlr:
            ctx.update({"p_model": _probs([mlr["ml_H"], mlr["ml_D"], mlr["ml_A"]]), "model_name": "ML historial"})
        ctx["stats"] = stats
        ctx.update({"source": "mercado" if ref_book else "modelo entre ligas", "xg": [_f(lam, 2), _f(mu, 2)],
                    "recommendation": {"bet": False, "text": (
                        "Sin modelo validado en esta liga: se muestra la probabilidad del mercado." if ref_book else
                        "Sin cuotas todavía: pronóstico del modelo entre ligas (Elo global + fuerza de cada liga).")}})
        if ref_book:
            ctx["p_market"] = _probs(p_off)
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
            """SELECT m.id, c.code, c.type, m.round, m.kickoff_utc, m.home_team_id, m.away_team_id,
                      th.name AS home, ta.name AS away
               FROM matches m JOIN competitions c ON c.id = m.competition_id
               JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id WHERE m.id = ?""",
            (match_id,)).fetchone()
        if r is None:
            raise KeyError(f"Partido {match_id} no encontrado")
        ctx = _build_context(f"m:{match_id}", r["code"], r["home"], r["away"], r["kickoff_utc"],
                             tracking.latest_market_odds(conn, match_id), r["home_team_id"], r["away_team_id"])
        if r["type"] == "cup" and r["round"]:          # fase de la copa (Champions: "League Stage - 3", "Final"...)
            ctx["round"] = r["round"]
        # Forma reciente de ambos (puntos G/E/P y detalle): solo partidos que empezaron antes de este partido y de
        # ahora (nunca uno en juego ni futuro).
        before = min(r["kickoff_utc"], repo.utc_now())
        teams = [r["home_team_id"], r["away_team_id"]]
        form = recent_form(conn, teams, before_kickoff=before)
        h, a = form.get(r["home_team_id"]), form.get(r["away_team_id"])
        if h or a:
            venue = recent_form(conn, teams, before_kickoff=before, venue_only=True)   # local en casa, visita fuera
            ctx["recent"] = {"home": h or [], "away": a or [], "home_venue": venue.get(r["home_team_id"], []),
                             "away_venue": venue.get(r["away_team_id"], [])}
        if r["type"] == "league":                      # posición y puntos de ambos en la tabla vigente
            from footy.web.services import standings

            summary = standings.summary(conn, r["code"], r["home_team_id"], r["away_team_id"])
            if summary:
                ctx["standings_summary"] = summary
        return ctx
    return _cached_context(f"m:{match_id}", build)


def sim_context(code: str, home: str, away: str, odds: list[float] | None) -> dict:
    ref = f"s:{code}|{home}|{away}|{','.join(map(str, odds or []))}"
    user_odds = {"1X2": {"Tu casa": dict(zip("HDA", odds))} if odds else {}, "OU": {}, "BTTS": {}}
    return _cached_context(ref, lambda: _build_context(ref, code, home, away, None, user_odds))


def cross_sim_context(home_league: str, away_league: str, home_id: int, away_id: int) -> dict:
    """Simulador entre ligas: probabilidades del modelo entre ligas (Elo global + ajuste por liga) para dos clubes
    cualesquiera. Sin cuotas: la probabilidad oficial es la del modelo."""
    from footy.models import cross_league

    model = cross_league.load()
    if model is None:
        raise KeyError("El modelo entre ligas no está entrenado (lo entrena scripts/daily.py)")
    conn = connect()
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM teams WHERE id IN (?, ?)", (home_id, away_id))}
    if home_id not in names or away_id not in names:
        raise KeyError("Equipo no encontrado")
    ref = f"x:{home_league}|{away_league}|{home_id}|{away_id}"
    p = model.probabilities(home_id, away_id)
    return _cached_context(ref, lambda: _build_context(ref, home_league, names[home_id], names[away_id], None,
                                                       {"1X2": {}, "OU": {}, "BTTS": {}}, home_id, away_id, p))


def context(ref: str) -> dict:
    if ref.startswith("m:"):
        return match_context(connect(), int(ref[2:]))
    if ref.startswith("x:"):
        hl, al, h, a = ref[2:].split("|")
        return cross_sim_context(hl, al, int(h), int(a))
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


def recent_form(conn, team_ids, before_kickoff: str | None = None, n: int = FORM_N,
                venue_only: bool = False) -> dict[int, list[dict]]:
    """Últimos `n` partidos terminados con marcador de cada equipo, del más antiguo al más reciente, en cualquier
    competición: resultado (W/D/L), marcador propio [a favor, en contra], rival, condición, fecha y competición.
    Anti-filtración: con `before_kickoff` solo cuentan partidos que empezaron antes. Una sola consulta para todos los
    equipos (ROW_NUMBER por equipo).
    Con `venue_only`, `team_ids` es (local, visita) del partido actual: el local solo cuenta sus partidos como local y
    la visita solo los de visita."""
    if venue_only:
        home, away = (int(t) for t in team_ids)
        home_ids, away_ids = [home], [away]
    else:
        home_ids = away_ids = sorted({int(t) for t in team_ids if t is not None})
    if not home_ids and not away_ids:
        return {}
    hmarks, amarks = ",".join("?" * len(home_ids)), ",".join("?" * len(away_ids))
    before = before_kickoff or "9999"
    rows = conn.execute(
        f"""WITH t AS (
              SELECT home_team_id AS team, away_team_id AS opp, 1 AS is_home, kickoff_utc, competition_id,
                     home_goals AS gf, away_goals AS ga FROM matches
              WHERE status = 'finished' AND home_goals IS NOT NULL AND kickoff_utc < ? AND home_team_id IN ({hmarks})
              UNION ALL
              SELECT away_team_id, home_team_id, 0, kickoff_utc, competition_id, away_goals, home_goals FROM matches
              WHERE status = 'finished' AND home_goals IS NOT NULL AND kickoff_utc < ? AND away_team_id IN ({amarks}))
            SELECT x.team, x.opp, o.name AS opp_name, x.is_home, x.kickoff_utc, c.code, x.gf, x.ga FROM (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY team ORDER BY kickoff_utc DESC) AS rn FROM t) x
            JOIN teams o ON o.id = x.opp JOIN competitions c ON c.id = x.competition_id
            WHERE x.rn <= ? ORDER BY x.team, x.kickoff_utc""", (before, *home_ids, before, *away_ids, n)).fetchall()
    names = league_names()
    out: dict[int, list[dict]] = {}
    for r in rows:
        gf, ga = r["gf"], r["ga"]
        out.setdefault(r["team"], []).append({
            "outcome": "W" if gf > ga else "D" if gf == ga else "L", "score": [gf, ga], "opponent": r["opp_name"],
            "opponent_id": r["opp"], "is_home": bool(r["is_home"]), "date": r["kickoff_utc"], "league": r["code"],
            "league_name": names.get(r["code"], r["code"])})
    return out


def _upcoming(days: int) -> list[dict]:
    conn = connect()
    now = datetime.now(timezone.utc)
    # Hasta el final del día `days - 1` desde hoy en hora local (hoy y mañana con days=2).
    local_today = datetime.now(LOCAL_TZ).date()
    end = datetime.combine(local_today + timedelta(days=days), datetime.min.time(), LOCAL_TZ)
    hidden = _hidden_codes()
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
    return out


# --- partidos ya jugados (ayer y hoy) ----------------------------------------

LIVE_WINDOW = timedelta(minutes=135)    # 90' + descanso + descuentos: después de esto ya debería haber terminado
LIVE_FRESH = timedelta(minutes=10)      # marcador parcial de ESPN que todavía se considera actual
LIVE_ON = timedelta(minutes=3)          # el servidor está actualizando en vivo si sincronizó hace menos de esto

def _hidden_codes() -> list[str]:
    return [c for c, v in config.settings()["competitions"].items() if v.get("history_only")]


def _play_status(status: str, has_score: bool, kickoff: str, now: datetime, live: bool = False) -> str:
    """Estado para mostrar. Con marcador en vivo reciente (ESPN), en juego. Si no, la base puede estar atrasada: un
    partido que ya empezó y sigue como programado está en juego si empezó hace menos de LIVE_WINDOW y, si no,
    esperando su resultado."""
    if status == "finished" and has_score:
        return "finished"
    if status in ("postponed", "cancelled"):
        return status
    if live:
        return "live"
    return "live" if now - repo.from_iso(kickoff) < LIVE_WINDOW else "pending"


def _synced(conn, name: str) -> str | None:
    row = conn.execute("SELECT synced_at FROM sync_log WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def last_fixtures_update(conn, start: datetime, end: datetime) -> str | None:
    """Hora UTC de la última descarga correcta del calendario de las fechas UTC que cubren [start, end): de ahí salen
    estados y resultados. Un día de Chile abarca dos fechas UTC; vale la más antigua de las dos."""
    days = sorted({start.astimezone(timezone.utc).date(), (end - timedelta(seconds=1)).astimezone(timezone.utc).date()})
    last = [conn.execute("""SELECT MAX(requested_at) FROM api_requests WHERE endpoint = 'fixtures' AND params = ?
                            AND errors IS NULL""", (json.dumps({"date": d.isoformat()}),)).fetchone()[0] for d in days]
    return None if None in last else min(last)


def played(day: str = "yesterday") -> dict:
    """Partidos ya jugados de ayer o de hoy (hora de Chile; hoy, solo los que ya empezaron) con su resultado y el
    pronóstico 1X2 que el sistema registró antes del inicio (el último de `predictions` anterior al kickoff; nunca
    uno posterior), para ver si acertó."""
    conn = connect()
    now = datetime.now(timezone.utc)
    start = datetime.combine(datetime.now(LOCAL_TZ).date() + timedelta(days={"yesterday": -1, "today": 0}[day]),
                             datetime.min.time(), LOCAL_TZ)
    end = min(start + timedelta(days=1), now + timedelta(seconds=1))
    live_at = _synced(conn, "espn_live")
    stamps = [s for s in (last_fixtures_update(conn, start, end), _synced(conn, "espn_calendar"), live_at) if s]
    return {"updated_at": max(stamps) if stamps else None,
            "live": bool(live_at and now - repo.from_iso(live_at) < LIVE_ON),
            "matches": _played_rows(conn, start, end, now)}


def _played_rows(conn, start: datetime, end: datetime, now: datetime) -> list[dict]:
    hidden = _hidden_codes()
    where_hidden = f"AND c.code NOT IN ({','.join('?' * len(hidden))})" if hidden else ""
    rows = conn.execute(
        f"""SELECT m.id, c.code, c.type, m.round, m.kickoff_utc, m.status, m.home_goals, m.away_goals,
                   m.home_team_id, m.away_team_id, th.name AS home, ta.name AS away
            FROM matches m JOIN competitions c ON c.id = m.competition_id
            JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id
            WHERE m.kickoff_utc >= ? AND m.kickoff_utc < ? {where_hidden}
            ORDER BY m.kickoff_utc, m.id""",
        (repo.to_iso(start), repo.to_iso(end), *hidden)).fetchall()
    if not rows:
        return []
    marks = ",".join("?" * len(rows))
    ids = [r["id"] for r in rows]
    fresh = repo.to_iso(now - LIVE_FRESH)
    live = {r["match_id"]: r for r in conn.execute(
        f"SELECT * FROM live_scores WHERE match_id IN ({marks}) AND updated_at >= ?", (*ids, fresh))}
    preds = {}
    for r in conn.execute(
            f"""SELECT p.match_id, p.p_home, p.p_draw, p.p_away, p.extra_json FROM predictions p
                JOIN matches m ON m.id = p.match_id
                WHERE p.match_id IN ({marks}) AND p.created_at < m.kickoff_utc
                ORDER BY p.created_at""", ids):
        extra = json.loads(r["extra_json"] or "{}")
        # La probabilidad oficial de ese momento (modelo + mercado) si había cuotas; si no, la del modelo.
        preds[r["match_id"]] = extra.get("p_final") or [r["p_home"], r["p_draw"], r["p_away"]]
    names = league_names()
    out = []
    for r in rows:
        item = {"ref": f"m:{r['id']}", "league": r["code"], "league_name": names.get(r["code"], r["code"]),
                "home": r["home"], "away": r["away"], "home_id": r["home_team_id"], "away_id": r["away_team_id"],
                "kickoff": r["kickoff_utc"]}
        finished = r["status"] == "finished" and r["home_goals"] is not None
        ls = None if finished else live.get(r["id"])
        item["status"] = _play_status(r["status"], finished, r["kickoff_utc"], now, live=ls is not None)
        if finished:
            item["score"] = [r["home_goals"], r["away_goals"]]
        elif ls is not None and item["status"] == "live":                 # marcador parcial y minuto (ESPN)
            item["score"] = [ls["home_goals"], ls["away_goals"]]
            if ls["clock"]:
                item["clock"] = ls["clock"]
        if r["type"] == "cup" and r["round"]:
            item["round"] = r["round"]
        p = preds.get(r["id"])
        if p:
            k = int(np.argmax(p))
            item["pick"] = {"sel": "1X2"[k], "p": _f(p[k])}
            if finished:
                diff = r["home_goals"] - r["away_goals"]
                item["pick"]["hit"] = k == (0 if diff > 0 else 1 if diff == 0 else 2)
        out.append(item)
    return out
