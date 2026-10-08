"""Selección de apuestas por EV y simulación de bankroll.

Regla: en cada partido se elige la selección con mayor EV = p_modelo * cuota - 1,
y se apuesta solo si EV > min_ev. Si ninguna supera el umbral: NO APOSTAR.
"""

import numpy as np
import pandas as pd

from footy.evaluation.metrics import bootstrap_mean_ci


def select_bets(P: np.ndarray, odds: np.ndarray, min_ev: float, max_odds: float = np.inf) -> pd.DataFrame:
    """Devuelve una fila por apuesta: idx (fila original), sel (0/1/2), p, odds, ev."""
    ev = P * odds - 1
    ev = np.where(np.isnan(odds) | (odds > max_odds), -np.inf, ev)
    sel = ev.argmax(axis=1)
    best = ev[np.arange(len(ev)), sel]
    idx = np.flatnonzero(best > min_ev)
    return pd.DataFrame({"idx": idx, "sel": sel[idx], "p": P[idx, sel[idx]],
                         "odds": odds[idx, sel[idx]], "ev": best[idx]})


def simulate(bets: pd.DataFrame, y: np.ndarray, staking: str = "flat", kelly_fraction: float = 0.25,
             max_stake: float = 0.05, bankroll: float = 100.0) -> dict:
    """Simula en orden cronológico (bets debe venir ordenado como los partidos).

    flat: 1 unidad por apuesta; drawdown en unidades.
    kelly: stake = fracción * kelly * bankroll, con tope `max_stake` del bankroll; drawdown en %.
    """
    won = y[bets.idx.to_numpy()] == bets.sel.to_numpy()
    o, p = bets.odds.to_numpy(), bets.p.to_numpy()
    if staking == "flat":
        stakes = np.ones(len(bets))
        profit = np.where(won, o - 1, -1.0)
        curve = np.concatenate([[0.0], np.cumsum(profit)])
        dd = float(np.max(np.maximum.accumulate(curve) - curve)) if len(curve) else 0.0
    else:
        b = bankroll
        stakes, profit, curve = [], [], [b]
        for oi, pi, wi in zip(o, p, won):
            f = min(max_stake, kelly_fraction * max(0.0, (pi * oi - 1) / (oi - 1)))
            s = f * b
            r = s * (oi - 1) if wi else -s
            b += r
            stakes.append(s), profit.append(r), curve.append(b)
        stakes, profit, curve = map(np.asarray, (stakes, profit, curve))
        peak = np.maximum.accumulate(curve)
        dd = float(np.max((peak - curve) / peak)) if len(curve) else 0.0

    per_bet = np.where(won, o - 1, -1.0)  # rendimiento por unidad apostada
    lo, hi = bootstrap_mean_ci(per_bet) if len(bets) >= 10 else (np.nan, np.nan)
    losing = max((len(s) for s in "".join("L" if not w else "W" for w in won).split("W")), default=0)
    return {
        "bets": len(bets),
        "hit_rate": float(won.mean()) if len(bets) else np.nan,
        "avg_odds": float(o.mean()) if len(bets) else np.nan,
        "yield": float(profit.sum() / stakes.sum()) if len(bets) else np.nan,
        "yield_ci": (lo, hi),
        "profit": float(profit.sum()),
        "max_drawdown": dd,
        "longest_losing_streak": losing,
        "curve": curve,
    }
