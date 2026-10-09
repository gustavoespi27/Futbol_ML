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
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from footy import config
from footy.betting.devig import proportional
from footy.db import repository as repo
from footy.db.connection import connect
from footy.evaluation import live
from footy.ingest.football_data import leagues as fd_leagues
from footy.leagues import load_params
from footy.markets import combos
from footy.prediction import tracking
from footy.prediction.predictor import LeaguePredictor

PREDICTOR_TTL = 6 * 3600
CONTEXT_TTL = 600
DISPLAY_BOOKS = ("Bet365", "Pinnacle", "Betfair Exchange", "Betfair", "Market Avg")   # cuota que se muestra
REFERENCE_BOOKS = ("Pinnacle", "Betfair Exchange", "Market Avg", "Bet365")             # para quitar el margen
STALE_DAYS = 12

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


def predictor(code: str) -> LeaguePredictor:
    """Predictor por liga, cacheado unas horas (ajustarlo toma 1-3 s)."""
    with _lock:
        hit = _predictors.get(code)
        if hit and time.time() - hit[0] < PREDICTOR_TTL:
            return hit[1]
        p = LeaguePredictor(code)
        _predictors[code] = (time.time(), p)
        return p


def clear_caches() -> None:
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
            out[k] = {"price": round(1 / (1 / x + 1 / y), 2), "book": book, "estimated": True}
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


def _build_context(ref: str, code: str, home: str, away: str, kickoff: str | None, odds: dict,
                   home_id: int | None = None, away_id: int | None = None) -> dict:
    params, names = load_params(), league_names()
    books = _books_1x2(odds)
    ref_book = next((b for b in REFERENCE_BOOKS if b in books), None) or next(iter(books), None)
    p_mkt_over = _market_over(odds)
    ctx = {"ref": ref, "league": code, "league_name": names.get(code, code), "home": home, "away": away,
           "kickoff": kickoff, "market_book": ref_book}
    if code in params:
        pred = predictor(code)
        if home_id is None:
            home_id, away_id = pred.find_team(home).id, pred.find_team(away).id
        pr = pred.probabilities(home_id, away_id, books[ref_book] if ref_book else None)
        p_off = pr.get("p_final", pr["p_model"])
        p_dc_over = float(combos.over_prob(pr["lam"], pr["mu"], pred.dc.rho)[0])
        p_over = float(combos.calibrate_over(np.array([p_dc_over]),
                                             None if p_mkt_over is None else np.array([p_mkt_over]),
                                             params[code].get("ou"))[0])
        M = combos.fit_matrix(pr["lam"], pr["mu"], pred.dc.rho, p_off, p_over)
        ctx.update({"source": "modelo + mercado" if ref_book else "modelo", "p_model": _probs(pr["p_model"]),
                    "p_market": _probs(pr.get("p_market")), "xg": [_f(pr["lam"], 2), _f(pr["mu"], 2)]})
        ctx["recommendation"] = _paper_bet(params[code], p_off, books) if ref_book else {
            "bet": False, "text": "Sin cuotas: no se puede evaluar valor."}
    elif ref_book:
        p_off = proportional(books[ref_book][None, :])[0]
        lam, mu = combos.implied_goals(p_off, p_mkt_over)
        M = combos.fit_matrix(lam, mu, 0.0, p_off, p_mkt_over)
        ctx.update({"source": "mercado", "p_market": _probs(p_off), "xg": [_f(lam, 2), _f(mu, 2)],
                    "recommendation": {"bet": False, "text": "Sin modelo validado en esta liga: se muestra la "
                                                              "probabilidad del mercado."}})
    else:
        ctx.update({"source": "sin datos", "p_official": None, "options": [], "suggestions": [],
                    "recommendation": {"bet": False, "text": "Sin modelo validado ni cuotas todavía."}})
        return ctx
    oo = _option_odds(odds)
    options = []
    for o in combos.options(M):
        bo = oo.get(o["key"])
        options.append({**o, "fair": _f(1 / o["p"], 2) if o["p"] > 0 else None,
                        "odds": bo["price"] if bo else None, "book": bo["book"] if bo else None,
                        "estimated": bo["estimated"] if bo else False,
                        "ev": _f(o["p"] * bo["price"] - 1) if bo else None})
    ctx.update({"p_official": _probs([combos.prob(M, [k]) for k in "1X2"]),
                "over25": _f(combos.prob(M, ["O2.5"])), "btts": _f(combos.prob(M, ["BTTS_Y"])),
                "top_scores": _top_scores(M), "options": options,
                "suggestions": [{**s, "fair": _f(1 / s["p"], 2)} for s in combos.suggestions(M)],
                "odds_1x2": {b: [round(float(x), 2) for x in v] for b, v in books.items() if b in DISPLAY_BOOKS},
                "_M": M})
    return ctx


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

def upcoming(days: int = 7) -> list[dict]:
    conn = connect()
    now = datetime.now(timezone.utc)
    ids = [r[0] for r in conn.execute(
        """SELECT m.id FROM matches m WHERE m.status = 'scheduled' AND m.kickoff_utc BETWEEN ? AND ?
           ORDER BY m.kickoff_utc""", (repo.to_iso(now), repo.to_iso(now + timedelta(days=days))))]
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
                       "kickoff": ctx.get("kickoff"), "keys": keys, "label": combos.label(keys), "p": _f(p),
                       "fair": _f(1 / p, 2) if p > 0 else None, "odds": _f(book, 2), "odds_source": book_src,
                       "impossible": p == 0, "same_match": len(keys) > 1})
        p_total *= p
        fair_total = fair_total * (1 / p) if p > 0 else None
        book_total = book_total * book if (book_total is not None and book) else None
    n = len(groups)
    hist = next((r for r in live.combo_backtest()["strategies"]["probables"] if r["legs"] == n), None) if n else None
    return {"groups": groups, "legs": n, "p": _f(p_total), "fair_odds": _f(fair_total, 2) if fair_total else None,
            "book_odds": _f(book_total, 2) if (n and book_total) else None,
            "ev": _f(p_total * book_total - 1) if (n and book_total) else None, "history": hist}


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
                            "fair": o["fair"], "home": m["home"], "away": m["away"], "league_name": m["league_name"],
                            "kickoff": m["kickoff"], "source": m["source"]})
    return out


def current_suggestions(matches: list[dict] | None = None) -> dict:
    from footy.betting import suggestions as sg

    cands = _candidates(matches if matches is not None else upcoming(7))
    singles = sg.pick_singles(cands)
    safest: dict = {}
    for c in cands:                                   # alta probabilidad (aunque el valor sea negativo)
        if not c["estimated"] and c["p"] >= 0.70 and c["odds"] >= 1.15:
            if c["match"] not in safest or c["p"] > safest[c["match"]]["p"]:
                safest[c["match"]] = {**c, "ev": c["p"] * c["odds"] - 1}
    chosen = {(x["match"], x["key"]) for x in singles}
    near = [{**c, "ev": c["p"] * c["odds"] - 1, "risk": sg.risk_level(c["p"])} for c in cands
            if not c["estimated"] and sg.MIN_ODDS <= c["odds"] <= sg.MAX_ODDS and c["p"] >= sg.MIN_P
            and (c["match"], c["key"]) not in chosen]
    closest: dict = {}
    for c in sorted(near, key=lambda c: -c["ev"]):
        closest.setdefault(c["match"], c)
    return {"rules": sg.RULES, "singles": singles, "doubles": sg.pick_doubles(singles),
            "closest": list(closest.values())[:6],
            "safest": sorted(safest.values(), key=lambda c: -c["p"])[:8],
            "n_matches_with_odds": len({c["match"] for c in cands})}


def suggestions_data() -> dict:
    from footy.prediction import suggested

    return {**current_suggestions(), "history": live.combo_backtest().get("suggestions", {}),
            "record": suggested.record(connect())}


def register_suggestions(conn=None) -> dict:
    """Guarda las sugerencias actuales (antes del partido) para medirlas después. Lo llama scripts/daily.py."""
    from footy.prediction import suggested

    cur = current_suggestions()
    return suggested.register(conn or connect(), cur["singles"], cur["doubles"], tracking.MODEL_VERSION)


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
                         "home": r["home"], "away": r["away"], "score": r["score"], "y": int(r["y"]),
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
