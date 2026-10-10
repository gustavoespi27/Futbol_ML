"""Evaluación: resumen del sistema, seguimiento prospectivo, evaluación fuera de muestra 2026, ML y ligas."""

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from footy import config
from footy.db.connection import connect
from footy.evaluation import live
from footy.leagues import load_params
from footy.prediction import tracking
from footy.web.services.catalog import league_names
from footy.web.services.common import _f, _probs, data_through


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


def ml_report() -> dict:
    path = config.path("processed") / "ml" / "report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


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


# --- ligas -----------------------------------------------------------------------

def leagues_list() -> list[dict]:
    params, names = load_params(), league_names()
    bt = {r["code"]: r for r in backtest()["per_league"]}
    through = data_through()
    return [{"code": c, "name": names.get(c, c), "status": p["status"], "min_ev": p["min_ev"],
             "max_odds": p.get("max_odds"), "w_blend": p["w_blend"], "w_models": p["w_models"],
             "data_through": through.get(c), "live": bt.get(c)}
            for c, p in sorted(params.items(), key=lambda kv: names.get(kv[0], kv[0]))]


def clear_caches() -> None:
    live.live_frame.cache_clear()
    live.combo_backtest.cache_clear()
