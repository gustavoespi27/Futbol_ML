"""Evaluación fuera de muestra sobre la temporada 2026 (período LIVE de los walk-forward).

Los pesos y calibraciones de config/league_models.json se ajustaron con 2016-2025, así que 2026 es examen.
Las probabilidades se reconstruyen desde las predicciones walk-forward guardadas por los análisis
(data/processed/{shots,screen}/wf_<liga>.csv) y las cuotas de cierre de la base.
"""

import json
from functools import lru_cache

import numpy as np
import pandas as pd

from footy import config
from footy.data import load_ou_closing
from footy.db.connection import connect
from footy.leagues import load_params
from footy.markets import combos
from footy.models.ensemble import pool

WF_DIRS = (config.path("processed") / "shots", config.path("processed") / "screen")
CANDIDATES = ("1", "X", "2", "O2.5", "U2.5")          # selecciones con cuota de cierre real en el histórico
ODDS_COL = {"1": "b365_H", "X": "b365_D", "2": "b365_A", "O2.5": "b365_over", "U2.5": "b365_under"}


def read_wf(code: str) -> pd.DataFrame | None:
    for d in WF_DIRS:
        p = d / f"wf_{code}.csv"
        if p.exists():
            return pd.read_csv(p)
    return None


@lru_cache
def live_frame() -> pd.DataFrame:
    """Un partido por fila con probabilidades 1X2 (modelo, mercado, oficial), Over 2,5 oficial y cuotas de cierre."""
    params = load_params()
    conn = connect()
    frames = []
    for code, prm in params.items():
        d = read_wf(code)
        if d is None:
            continue
        d = d[(d.period == "live") & d["Mercado_pH"].notna()].copy()
        g = lambda m: d[[f"{m}_pH", f"{m}_pD", f"{m}_pA"]].to_numpy()  # noqa: E731
        Pe, Pd, Pm = g("Elo"), g("Dixon-Coles"), g("Mercado")
        d[["mo_H", "mo_D", "mo_A"]] = pool([Pe, Pd], np.array(prm["w_models"]))
        d[["of_H", "of_D", "of_A"]] = pool([Pe, Pd, Pm], np.array(prm["w_blend"]))
        d[["mk_H", "mk_D", "mk_A"]] = Pm
        d["code"], d["min_ev"], d["max_odds"] = code, prm["min_ev"], prm.get("max_odds", np.inf)
        d["rho"] = prm.get("rho", 0.0)
        ou = load_ou_closing(conn, d.match_id)
        d = d.merge(ou, left_on="match_id", right_index=True, how="left")
        p_dc = combos.over_prob(d.lam.to_numpy(), d.mu.to_numpy(), d.rho.iloc[0] if len(d) else 0.0)
        p_mkt = d.p_over.to_numpy()
        has = ~np.isnan(p_mkt)
        d["over_off"] = combos.calibrate_over(p_dc, None, prm.get("ou"))
        if has.any():
            d.loc[has, "over_off"] = combos.calibrate_over(p_dc[has], p_mkt[has], prm.get("ou"))
        d["over_dc"] = p_dc
        frames.append(d)
    df = pd.concat(frames, ignore_index=True).sort_values("kickoff_utc").reset_index(drop=True)
    df["week"] = pd.to_datetime(df.kickoff_utc).dt.strftime("%G-%V")
    return df


def _ci(x: np.ndarray) -> list[float] | None:
    if len(x) < 2:
        return None
    se = x.std(ddof=1) / np.sqrt(len(x))
    return [round(float(x.mean() - 1.96 * se), 4), round(float(x.mean() + 1.96 * se), 4)]


CACHE_PATH = config.path("processed") / "combo_backtest.json"


@lru_cache
def combo_backtest(max_legs: int = 4) -> dict:
    """Igual que _combo_backtest, guardado en disco mientras no cambien los parámetros de las ligas."""
    from footy.leagues import PARAMS_PATH

    key = f"{PARAMS_PATH.stat().st_mtime_ns}|{max_legs}|v2"
    if CACHE_PATH.exists():
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("_key") == key:
            return cached
    res = _combo_backtest(max_legs)
    CACHE_PATH.write_text(json.dumps({**res, "_key": key}, ensure_ascii=False), encoding="utf-8")
    return res


def _combo_backtest(max_legs: int = 4) -> dict:
    """¿Qué tan fiables y rentables habrían sido las combinadas en 2026?

    Para cada partido se ajusta la matriz de marcadores a las probabilidades oficiales (1X2 y Over 2,5).
    Estrategias, por semana y con un partido por pierna:
      - "probables": la selección más probable de cada partido; se combinan las más probables de la semana.
      - "valor": la selección con mayor EV (cuota <= max_odds de la liga); se combinan las de mayor EV.
    Se apuesta a cuota de cierre de Bet365 (1X2 y O/U 2,5), 1 unidad por combinada.
    """
    df = live_frame()
    rows = df.dropna(subset=["b365_H", "b365_D", "b365_A"]).reset_index(drop=True)
    goals = list(zip(rows.home_goals.astype(int), rows.away_goals.astype(int)))
    legs, same_game, pattern_rows = [], [], []
    pairs = _pattern_keys()
    for i, r in enumerate(rows.itertuples(index=False)):
        has_ou = not np.isnan(r.over_off)
        M = combos.fit_matrix(r.lam, r.mu, r.rho, [r.of_H, r.of_D, r.of_A], r.over_off if has_ou else None)
        h, a = goals[i]
        for k in CANDIDATES:
            odds = getattr(r, ODDS_COL[k], np.nan)
            if odds is None or np.isnan(odds):
                continue
            p = combos.prob(M, [k])
            legs.append((r.week, i, k, p, float(odds), combos.pattern_hits(h, a, [k]), p * odds - 1, r.max_odds,
                         r.kickoff_utc[:10]))
        sug = combos.suggestions(M, top=1)
        if sug:
            same_game.append((sug[0]["p"], combos.pattern_hits(h, a, sug[0]["keys"])))
        pattern_rows.append([r.code] + [v for keys in pairs for v in (combos.prob(M, keys),
                                                                      combos.pattern_hits(h, a, keys))])
    L = pd.DataFrame(legs, columns=["week", "match", "key", "p", "odds", "hit", "ev", "max_odds", "date"])

    strategies = {}
    calib_pts = []
    for name in ("probables", "valor"):
        if name == "probables":
            pick = L.loc[L.groupby("match").p.idxmax()]
            order = "p"
        else:
            ok = L[(L.odds <= L.max_odds) & (L.ev > 0)]
            pick = ok.loc[ok.groupby("match").ev.idxmax()]
            order = "ev"
        res = []
        for k in range(1, max_legs + 1):
            combos_k = []
            for _, wk in pick.groupby("week"):
                wk = wk.sort_values(order, ascending=False)
                for j in range(0, len(wk) - k + 1, k):
                    g = wk.iloc[j:j + k]
                    combos_k.append((float(np.prod(g.p)), float(np.prod(g.odds)), bool(g.hit.all())))
            if not combos_k:
                continue
            C = np.array(combos_k)
            profit = np.where(C[:, 2] == 1, C[:, 1] - 1, -1.0)
            res.append({"legs": k, "n": len(C), "p_mean": round(float(C[:, 0].mean()), 4),
                        "hit": round(float(C[:, 2].mean()), 4), "odds_mean": round(float(np.median(C[:, 1])), 2),
                        "yield": round(float(profit.mean()), 4), "ci": _ci(profit)})
            if name == "probables" and k >= 2:
                calib_pts += [(c[0], c[2]) for c in combos_k]
        strategies[name] = res

    return {"n_matches": len(rows), "n_ou": int(rows.b365_over.notna().sum()),
            "from": rows.kickoff_utc.min()[:10], "to": rows.kickoff_utc.max()[:10],
            "strategies": strategies, "calibration": _bins(calib_pts), "same_game_calibration": _bins(same_game),
            "patterns": _patterns(pattern_rows, pairs), "suggestions": _suggestion_backtest(L)}


def _suggestion_backtest(L: pd.DataFrame) -> dict:
    """La regla de "apuestas sugeridas" (footy.betting.suggestions) aplicada a 2026, en orden cronológico."""
    from footy.betting import suggestions as sg

    singles = pd.DataFrame(sg.pick_singles(L.to_dict("records"))).sort_values(["date", "match"])
    out = {"rules": sg.RULES}
    if singles.empty:
        return out
    flat = np.where(singles.hit, singles.odds - 1, -1.0)
    bank, curve, peak, max_dd = 100.0, [], 100.0, 0.0
    for r, (_, row) in zip(flat, singles.iterrows()):
        bank *= 1 + row.stake * r
        peak = max(peak, bank)
        max_dd = max(max_dd, 1 - bank / peak)
        curve.append((row.date, round(bank, 2)))
    step = max(1, len(curve) // 150)
    by_risk = []
    for lvl in ("bajo", "medio", "alto"):
        m = (singles.risk == lvl).to_numpy()
        if m.sum():
            by_risk.append({"risk": lvl, "n": int(m.sum()), "hit": round(float(singles.hit[m].mean()), 4),
                            "p_mean": round(float(singles.p[m].mean()), 4), "yield": round(float(flat[m].mean()), 4),
                            "ci": _ci(flat[m])})
    by_key = singles.assign(profit=flat).groupby("key").agg(n=("hit", "size"), hit=("hit", "mean"),
                                                             yield_=("profit", "mean")).reset_index()
    doubles = []
    for _, wk in singles.groupby("week"):
        wk = wk.sort_values("growth", ascending=False)
        for j in range(0, len(wk) - 1, 2):
            a, b = wk.iloc[j], wk.iloc[j + 1]
            doubles.append(a.odds * b.odds - 1 if a.hit and b.hit else -1.0)
    doubles = np.array(doubles)
    out.update({
        "n": len(singles), "hit": round(float(singles.hit.mean()), 4), "p_mean": round(float(singles.p.mean()), 4),
        "odds_mean": round(float(singles.odds.mean()), 2), "ev_mean": round(float(singles.ev.mean()), 4),
        "yield": round(float(flat.mean()), 4), "ci": _ci(flat), "profit_units": round(float(flat.sum()), 1),
        "kelly_final": round(bank, 2), "kelly_max_dd": round(max_dd, 4),
        "curve": [{"d": d, "b": b} for d, b in curve[::step]] + [{"d": curve[-1][0], "b": curve[-1][1]}],
        "by_risk": by_risk,
        "by_key": [{"key": r.key, "n": int(r.n), "hit": round(float(r.hit), 4), "yield": round(float(r.yield_), 4)}
                   for r in by_key.itertuples()],
        "doubles": {"n": len(doubles), "yield": round(float(doubles.mean()), 4) if len(doubles) else None,
                    "hit": round(float((doubles > -1).mean()), 4) if len(doubles) else None, "ci": _ci(doubles)},
    })
    return out


def _bins(points, edges=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.01), min_n=30) -> list[dict]:
    if not points:
        return []
    P = np.array(points, dtype=float)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (P[:, 0] >= lo) & (P[:, 0] < hi)
        if m.sum() >= min_n:
            out.append({"pred": round(float(P[m, 0].mean()), 4), "obs": round(float(P[m, 1].mean()), 4),
                        "n": int(m.sum())})
    return out


def _pattern_keys() -> list[list[str]]:
    res = ["1", "X", "2", "1X", "X2", "12"]
    goals = ["O1.5", "U1.5", "O2.5", "U2.5", "O3.5", "U3.5", "BTTS_Y", "BTTS_N"]
    return [[r, g] for r in res for g in goals] + [["O2.5", "BTTS_Y"], ["U2.5", "BTTS_N"], ["O1.5", "BTTS_Y"]]


def _patterns(rows: list, pairs: list[list[str]]) -> dict:
    """Frecuencia real de cada combinación de un mismo partido y la probabilidad media que le dio el sistema."""
    cols = ["code"] + [f"{j}_{t}" for j in range(len(pairs)) for t in ("p", "hit")]
    df = pd.DataFrame(rows, columns=cols)

    def table(d: pd.DataFrame) -> list[dict]:
        out = [{"keys": keys, "label": combos.label(keys), "n": len(d),
                "freq": round(float(d[f"{j}_hit"].mean()), 4), "pred": round(float(d[f"{j}_p"].mean()), 4)}
               for j, keys in enumerate(pairs)]
        return sorted(out, key=lambda r: -r["freq"])

    return {"all": table(df), "by_league": {c: table(g) for c, g in df.groupby("code") if len(g) >= 60}}
