"""Consolida en config/league_models.json los parámetros elegidos en VALIDACIÓN por liga.

Fuente: análisis 04 (con tiros) si existe para la liga; si no, análisis 03.
Los hiperparámetros de Elo y Dixon-Coles vienen de VALIDACIÓN (2016-21). Con las predicciones walk-forward
de 2016-2025 (validación + test; v3, ver docs/decisiones.md 2026-10-09) se ajustan:
- pesos Elo+DC (solo modelo) y Elo+DC+Mercado, ambos >= 0;
- umbral de EV, apostando a cuota Pinnacle y solo con cuotas <= MAX_ODDS (sesgo favorito-longshot);
- calibración de Over/Under 2,5: Dixon-Coles solo y combinado con el mercado (ligas con cuotas O/U);
- rho de Dixon-Coles con todos los datos (para recalcular matrices de marcadores en los históricos).
2026 queda fuera de todos estos ajustes y es la evaluación (dashboard, sección "¿Qué tan fiable es?").

Uso:  python scripts/build_league_models.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import screen_leagues as sl  # noqa: E402
from scipy.optimize import minimize  # noqa: E402

from footy import config  # noqa: E402
from footy.betting.backtest import select_bets, simulate  # noqa: E402
from footy.data import load_ou_closing  # noqa: E402
from footy.db.connection import connect  # noqa: E402
from footy.evaluation.pipeline import EV_GRID, MIN_VAL_BETS  # noqa: E402
from footy.ingest.football_data import leagues  # noqa: E402
from footy.leagues import PARAMS_PATH  # noqa: E402
from footy.markets.combos import logit, over_prob  # noqa: E402
from footy.models.ensemble import fit_weights, pool  # noqa: E402
from footy.prediction.predictor import LeaguePredictor  # noqa: E402

MAX_ODDS = 4.0
TRAIN_PERIODS = ("val", "test")          # 2016-2025

SHOTS = config.path("processed") / "shots"

STATUS = {
    "CONFIRMADA": ("pasó el criterio pre-registrado, pero sin significancia tras corregir por 38 ligas "
                   "(seguimiento prospectivo)"),
    "candidata (falla en test)": "sin ventaja demostrada (candidata en validación, falló en test)",
    "no": "sin ventaja demostrada",
}


def choose_min_ev(P: np.ndarray, odds: np.ndarray, y: np.ndarray) -> float:
    """Umbral con mejor yield en validación (mínimo MIN_VAL_BETS apuestas); si ninguno llega, el más exigente."""
    best, best_yield = EV_GRID[-1], -np.inf
    for thr in EV_GRID:
        bets = select_bets(P, odds, thr, max_odds=MAX_ODDS)
        if len(bets) >= MIN_VAL_BETS:
            r = simulate(bets, y)
            if r["yield"] > best_yield:
                best, best_yield = thr, r["yield"]
    return best


def fit_ou(p_dc: np.ndarray, p_mkt: np.ndarray, y: np.ndarray) -> dict:
    """Pesos logísticos (>= 0 para modelo y mercado) de Over 2,5: solo modelo y modelo + mercado."""
    def nll(z):
        p = np.clip(1 / (1 + np.exp(-z)), 1e-9, 1 - 1e-9)
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    ld, lm = logit(p_dc), logit(p_mkt)
    dc = minimize(lambda w: nll(w[0] * ld + w[1]), [1, 0], method="L-BFGS-B", bounds=[(0, 3), (-2, 2)]).x
    bl = minimize(lambda w: nll(w[0] * ld + w[1] * lm + w[2]), [0.1, 0.9, 0], method="L-BFGS-B",
                  bounds=[(0, 3), (0, 3), (-2, 2)]).x
    return {"dc": dc.round(4).tolist(), "blend": bl.round(4).tolist(), "n": int(len(y))}


def main() -> int:
    cfg = leagues()
    out, ou_rows = {}, []
    conn = connect()
    for code in [*cfg["extra"], *cfg["main"]]:
        src = SHOTS if (SHOTS / f"{code}.json").exists() else sl.CACHE
        if not (src / f"{code}.json").exists():
            continue
        r = json.loads((src / f"{code}.json").read_text(encoding="utf-8"))
        base = json.loads((sl.CACHE / f"{code}.json").read_text(encoding="utf-8"))
        wf = pd.read_csv(src / f"wf_{code}.csv")
        v = wf[wf.period.isin(TRAIN_PERIODS) & wf[["pin_H", "pin_D", "pin_A"]].notna().all(axis=1)]
        Ps = [v[[f"{m}_pH", f"{m}_pD", f"{m}_pA"]].to_numpy() for m in ("Elo", "Dixon-Coles", "Mercado")]
        y = v.y.to_numpy()
        w_blend = fit_weights(Ps, y, nonneg=True)
        out[code] = {
            "dixon_coles": r["dc_params"],
            "elo": r["elo_params"],
            "w_models": fit_weights(Ps[:2], y, nonneg=True).round(4).tolist(),
            "w_blend": w_blend.round(4).tolist(),
            "min_ev": choose_min_ev(pool(Ps, w_blend), v[["pin_H", "pin_D", "pin_A"]].to_numpy(), y),
            "max_odds": MAX_ODDS,
            "status": STATUS[sl.classify(base)],
            "source": "análisis 04 (tiros)" if src == SHOTS else "análisis 03",
            "trained_on": "2016-2025",
            "rho": round(float(LeaguePredictor(code).dc.rho), 4),
        }
        ou = load_ou_closing(conn, wf.match_id)
        t = wf[wf.period.isin(TRAIN_PERIODS)].merge(ou, left_on="match_id", right_index=True)
        if len(t) >= 500:
            p_dc = over_prob(t.lam.to_numpy(), t.mu.to_numpy(), out[code]["rho"])
            ou_rows.append((p_dc, t.p_over.to_numpy(), (t.home_goals + t.away_goals > 2.5).to_numpy(float)))
            out[code]["ou"] = fit_ou(*ou_rows[-1])
        print(code, out[code]["w_blend"], out[code].get("ou", {}).get("blend"))
    if ou_rows:                        # ligas sin historial de cuotas O/U: calibración común de las que sí tienen
        common = fit_ou(*(np.concatenate(x) for x in zip(*ou_rows)))
        for code in out:
            out[code].setdefault("ou", {**common, "shared": True})
    PARAMS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                           newline="\n")
    print(f"{len(out)} ligas -> {PARAMS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
