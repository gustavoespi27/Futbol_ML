"""Evaluación completa de una liga: ajuste en validación, evaluación única en test.

Períodos (por fecha de kickoff):
  historial previo : todo lo anterior a VAL (calentamiento de Elo y del ajuste)
  VALIDACIÓN       : se eligen hiperparámetros, pesos del ensamble y umbral de EV
  TEST             : se evalúa UNA vez con todo lo elegido en validación
  LIVE             : temporada en curso (sin Pinnacle; se compara contra el promedio)

Nada de lo que se elige mira TEST ni LIVE.
"""

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from footy.betting.backtest import select_bets, simulate
from footy.betting.devig import proportional
from footy.data import has_odds, odds_matrix
from footy.evaluation import metrics
from footy.evaluation.walk_forward import naive_frequencies, probs, walk_forward_dc, walk_forward_elo
from footy.models.ensemble import fit_weights, pool

PERIODS = {"val": ("2016-01-01", "2022-01-01"), "test": ("2022-01-01", "2026-01-01"),
           "live": ("2026-01-01", "2100-01-01")}

# Si un valor elegido cae en el borde de la grilla, hay que ampliarla (el óptimo podría estar fuera).
DC_GRID = {"xi": [0.0005, 0.001, 0.002, 0.003, 0.005], "alpha": [1e-3, 3e-3, 1e-2, 3e-2, 0.1]}
ELO_GRID = {"k": [8, 12, 16, 20, 30], "home_adv": [10, 30, 50, 70, 90, 110, 130],
            "new_team_offset": [25, 50, 100, 150], "season_regress": [0.0, 0.1, 0.3]}
EV_GRID = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15]
MIN_VAL_BETS = 100
BETFAIR_COMMISSION = 0.05


@dataclass
class LeagueResult:
    code: str
    dc_params: dict
    elo_params: dict
    weights_models: np.ndarray
    weights_market: np.ndarray
    metrics: pd.DataFrame
    betting: pd.DataFrame
    chosen: dict
    frame: pd.DataFrame = field(repr=False)
    curves: dict = field(repr=False, default_factory=dict)


def _period_mask(df, name):
    lo, hi = PERIODS[name]
    return ((df.kickoff >= lo) & (df.kickoff < hi)).to_numpy()


def _ll(df, pred, eval_mask):
    sub = df[eval_mask]
    ok = has_odds(sub, "pin")
    P = probs(pred)[ok]
    return metrics.log_loss(sub.y.to_numpy()[ok], P)


def _dc(df: pd.DataFrame, mask: np.ndarray, dc_comps: list[str] | None, **params) -> pd.DataFrame:
    """Dixon-Coles entrenado solo con `dc_comps` (más rápido que todo el país).
    El orden de salida coincide con df[mask] porque ambos van por kickoff."""
    if dc_comps is None:
        return walk_forward_dc(df, mask, **params)
    keep = df.comp.isin(dc_comps).to_numpy()
    return walk_forward_dc(df[keep].reset_index(drop=True), mask[keep], **params)


def tune(df: pd.DataFrame, eval_comp: str, dc_grid: dict = DC_GRID, elo_grid: dict = ELO_GRID,
         dc_comps: list[str] | None = None) -> tuple[dict, dict]:
    val = _period_mask(df, "val") & (df.comp == eval_comp).to_numpy()
    best_dc = min((dict(zip(dc_grid, v)) for v in itertools.product(*dc_grid.values())),
                  key=lambda p: _ll(df, _dc(df, val, dc_comps, **p), val))
    best_elo = min((dict(zip(elo_grid, v)) for v in itertools.product(*elo_grid.values())),
                   key=lambda p: _ll(df, walk_forward_elo(df, val, **p), val))
    return best_dc, best_elo


def evaluate(df: pd.DataFrame, eval_comp: str, dc_params: dict, elo_params: dict,
             dc_comps: list[str] | None = None) -> LeagueResult:
    mask = (df.kickoff >= PERIODS["val"][0]).to_numpy() & (df.comp == eval_comp).to_numpy()
    dc = _dc(df, mask, dc_comps, **dc_params)
    elo = walk_forward_elo(df, mask, **elo_params)
    f = df[mask].reset_index(drop=True)
    naive = naive_frequencies(df)[mask]
    f["period"] = np.select([_period_mask(f, "val"), _period_mask(f, "test")], ["val", "test"], "live")
    P = {"Naive": naive, "Elo": probs(elo), "Dixon-Coles": probs(dc)}
    f["lam"], f["mu"] = dc.lam.to_numpy(), dc.mu.to_numpy()

    # Referencia de mercado: Pinnacle si existe; si no (2026), promedio del mercado.
    pin_ok, avg_ok = has_odds(f, "pin"), has_odds(f, "avg")
    mkt = np.full((len(f), 3), np.nan)
    mkt[avg_ok] = proportional(odds_matrix(f[avg_ok], "avg"))
    mkt[pin_ok] = proportional(odds_matrix(f[pin_ok], "pin"))
    P["Mercado"] = mkt

    # Pesos en VALIDACIÓN (partidos con Pinnacle)
    v = (f.period == "val").to_numpy() & pin_ok
    y = f.y.to_numpy()
    w_models = fit_weights([P["Elo"][v], P["Dixon-Coles"][v]], y[v])
    w_market = fit_weights([P["Elo"][v], P["Dixon-Coles"][v], P["Mercado"][v]], y[v])
    P["Elo+DC"] = pool([P["Elo"], P["Dixon-Coles"]], w_models)
    ok_mkt = ~np.isnan(mkt).any(axis=1)
    blend = np.full((len(f), 3), np.nan)
    blend[ok_mkt] = pool([P["Elo"][ok_mkt], P["Dixon-Coles"][ok_mkt], mkt[ok_mkt]], w_market)
    P["Elo+DC+Mercado"] = blend

    rows = []
    for period in ("val", "test", "live"):
        m = (f.period == period).to_numpy() & ok_mkt
        if period != "live":
            m = m & pin_ok
        if m.sum() == 0:
            continue
        for name, Pm in P.items():
            rows.append({"periodo": period, "modelo": name, **metrics.summary(y[m], Pm[m])})
    met = pd.DataFrame(rows)

    betting, chosen, curves = _betting(f, P, y, pin_ok)
    for name, Pm in P.items():
        f[[f"{name}_pH", f"{name}_pD", f"{name}_pA"]] = Pm
    return LeagueResult(eval_comp, dc_params, elo_params, w_models, w_market, met, betting, chosen, f, curves)


def _betting(f, P, y, pin_ok):
    """Umbral de EV elegido en VAL (a cuota Pinnacle); aplicado en TEST a Pinnacle, Avg y Max."""
    rows, chosen, curves = [], {}, {}
    strategies = ("Elo+DC", "Elo+DC+Mercado")
    for strat in strategies:
        v = (f.period == "val").to_numpy() & pin_ok
        best, best_yield = None, -np.inf
        for thr in EV_GRID:
            bets = select_bets(P[strat][v], odds_matrix(f[v], "pin"), thr)
            r = simulate(bets, y[v])
            rows.append({"estrategia": strat, "periodo": "val", "cuota": "Pinnacle", "min_ev": thr, **_fmt(r)})
            if r["bets"] >= MIN_VAL_BETS and r["yield"] > best_yield:
                best, best_yield = thr, r["yield"]
        best = EV_GRID[-1] if best is None else best
        chosen[strat] = best

        for period, book in (("test", "pin"), ("test", "avg"), ("test", "max"), ("live", "avg"), ("live", "bfe")):
            m = (f.period == period).to_numpy()
            if period == "test":
                m = m & pin_ok
            odds = odds_matrix(f[m], book)
            if book == "bfe":
                odds = 1 + (odds - 1) * (1 - BETFAIR_COMMISSION)
            for thr in EV_GRID:
                bets = select_bets(P[strat][m], odds, thr)
                if bets.empty:
                    continue
                r = simulate(bets, y[m])
                rk = simulate(bets, y[m], staking="kelly")
                label = {"pin": "Pinnacle", "avg": "Promedio", "max": "Máxima", "bfe": "Betfair (-5% com.)"}[book]
                rows.append({"estrategia": strat, "periodo": period, "cuota": label, "min_ev": thr, **_fmt(r),
                             "kelly_profit_%": rk["profit"], "kelly_max_dd": rk["max_drawdown"],
                             "elegido_en_val": thr == best})
                if thr == best:
                    curves[(strat, period, label)] = r["curve"]
                    if period == "test":
                        sel = bets.sel.map({0: "Local", 1: "Empate", 2: "Visita"}).value_counts().to_dict()
                        rows[-1]["mix"] = ", ".join(f"{k} {v}" for k, v in sel.items())
    return pd.DataFrame(rows), chosen, curves


def _fmt(r):
    lo, hi = r["yield_ci"]
    return {"apuestas": r["bets"], "acierto": r["hit_rate"], "cuota_media": r["avg_odds"],
            "yield": r["yield"], "yield_ic95": f"[{lo:+.1%}, {hi:+.1%}]" if r["bets"] >= 10 else "",
            "max_dd_u": r["max_drawdown"], "racha_perd": r["longest_losing_streak"]}
