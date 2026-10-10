"""Modelo de machine learning (gradient boosting) sobre el historial de los equipos.

Dos regresiones Poisson predicen los goles esperados del local (λ) y de la visita (μ); 1X2, más de 2,5 goles y ambos
marcan salen de la MISMA matriz de marcadores (Poisson con la corrección de Dixon-Coles, rho ajustado en VALID), así
que son coherentes entre sí. En 2026 mejora el log loss 1X2 frente a tres clasificadores separados (1,0207 vs 1,0227,
IC95% de la diferencia −0,0037 a −0,0004) e iguala en más/menos y ambos marcan (ver docs/decisiones.md).
Variables: footy.features.history (forma, tiros, localía, temporada, rachas, descanso, enfrentamientos directos,
contexto de liga) + liga como categoría + (opcional) predicciones walk-forward de Elo y Dixon-Coles.

Períodos (por kickoff), sin mirar nunca el siguiente:
  TRAIN  2014-07 → 2023      ajuste
  VALID  2024 → 2025         elección de hiperparámetros, número de árboles, rho y pesos de la mezcla con el mercado
  TEST   2026 →              evaluación única (el modelo final se reentrena con TRAIN + VALID)
"""

import json
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.ensemble import HistGradientBoostingRegressor

from footy import config
from footy.features.history import feature_columns
from footy.markets.scoreline import MAX_GOALS, score_matrices

TRAIN_FROM, VALID_FROM, TEST_FROM = "2014-07-01", "2024-01-01", "2026-01-01"
ARTIFACTS = config.PROJECT_ROOT / "artifacts" / "ml"
ELO_DC_COLS = ["Elo_pH", "Elo_pD", "Elo_pA", "Dixon-Coles_pH", "Dixon-Coles_pD", "Dixon-Coles_pA", "lam", "mu"]
GRID = [{"learning_rate": lr, "max_leaf_nodes": leaves, "min_samples_leaf": leaf, "l2_regularization": 1.0}
        for lr in (0.04,) for leaves in (15, 31) for leaf in (200, 800)]
TASKS = ("1x2", "over25", "btts")                   # mercados que salen de la matriz de marcadores
SIDES = {"lam": "home_goals", "mu": "away_goals"}
_G = np.arange(MAX_GOALS + 1)
_TOTAL = _G[:, None] + _G[None, :]


def targets(df: pd.DataFrame) -> dict[str, np.ndarray]:
    hg, ag = df.home_goals.to_numpy(float), df.away_goals.to_numpy(float)
    return {"1x2": np.select([hg > ag, hg == ag], [0, 1], 2),
            "over25": (hg + ag > 2.5).astype(int), "btts": ((hg > 0) & (ag > 0)).astype(int)}


def design(df: pd.DataFrame, use_elo_dc: bool, comps: list[str]) -> pd.DataFrame:
    cols = feature_columns(df)
    X = df[cols].astype(float).copy()
    X["comp"] = pd.Categorical(df.comp, categories=comps)
    if use_elo_dc:
        for c in ELO_DC_COLS:
            X[c] = df[c].astype(float) if c in df else np.nan
    return X


def _logloss(P: np.ndarray, y: np.ndarray) -> float:
    if P.ndim == 1:
        p = np.clip(P, 1e-9, 1 - 1e-9)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], 1e-12, 1))))


def poisson_deviance(y: np.ndarray, mu: np.ndarray) -> float:
    mu = np.clip(mu, 1e-9, None)
    ylog = np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0.0)
    return float(np.mean(2 * (ylog - (y - mu))))


def goal_markets(lam: np.ndarray, mu: np.ndarray, rho: float) -> dict[str, np.ndarray]:
    """1X2 (n, 3), más de 2,5 y ambos marcan (n,) desde la misma matriz de marcadores de cada partido."""
    m = score_matrices(lam, mu, rho)
    home = np.tril(np.ones_like(_TOTAL), -1)
    p1x2 = np.stack([(m * home).sum(axis=(1, 2)), np.trace(m, axis1=1, axis2=2), (m * home.T).sum(axis=(1, 2))], 1)
    return {"1x2": p1x2, "over25": (m * (_TOTAL > 2.5)).sum(axis=(1, 2)), "btts": m[:, 1:, 1:].sum(axis=(1, 2))}


def _new(params: dict, max_iter: int, early: bool) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="poisson", **params, max_iter=max_iter, early_stopping=early, validation_fraction=0.1 if early else None,
        n_iter_no_change=30, categorical_features="from_dtype", random_state=0)


@dataclass
class PoissonGoalModel:
    use_elo_dc: bool
    comps: list[str]
    params: dict                    # {"lam": {...}, "mu": {...}}
    n_iter: dict                    # {"lam": int, "mu": int}
    rho: float
    valid_logloss: dict             # log loss en VALID de cada mercado
    models: dict = field(repr=False, default=None)   # {"lam": regresor, "mu": regresor}

    def goals(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        X = design(df, self.use_elo_dc, self.comps)
        return self.models["lam"].predict(X), self.models["mu"].predict(X)

    def predict(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        return goal_markets(*self.goals(df), self.rho)


def _rows(df: pd.DataFrame, use_elo_dc: bool) -> tuple[np.ndarray, np.ndarray]:
    k = df.kickoff_utc
    start = TRAIN_FROM if not use_elo_dc else "2016-01-01"
    tr = ((k >= start) & (k < VALID_FROM)).to_numpy()
    va = ((k >= VALID_FROM) & (k < TEST_FROM)).to_numpy()
    if use_elo_dc:
        has = df[ELO_DC_COLS[0]].notna().to_numpy()
        tr, va = tr & has, va & has
    return tr, va


def fit(df: pd.DataFrame, use_elo_dc: bool, log=print) -> tuple[PoissonGoalModel, dict[str, np.ndarray]]:
    """Elige hiperparámetros de λ y μ en VALID (devianza Poisson) y rho (log loss 1X2), reentrena con TRAIN+VALID.
    Devuelve el modelo y sus probabilidades de VALID hechas con el modelo de solo TRAIN (para la mezcla con el
    mercado sin mirar el futuro)."""
    comps = sorted(df.comp.unique())
    tr, va = _rows(df, use_elo_dc)
    X = design(df, use_elo_dc, comps)
    params, n_iter, valid_goals = {}, {}, {}
    for side, col in SIDES.items():
        y = df[col].to_numpy(float)
        best = None
        for p in GRID:
            m = _new(p, 1000, early=True).fit(X[tr], y[tr])
            pred = m.predict(X[va])
            dev = poisson_deviance(y[va], pred)
            log(f"  {side} elo_dc={use_elo_dc} {p} árboles={m.n_iter_} devianza VALID={dev:.5f}")
            if best is None or dev < best[0]:
                best = (dev, p, m.n_iter_, pred)
        _, params[side], n_iter[side], valid_goals[side] = best
    y1 = targets(df)["1x2"][va]
    rho = float(minimize_scalar(lambda r: _logloss(goal_markets(valid_goals["lam"], valid_goals["mu"], r)["1x2"], y1),
                                bounds=(-0.2, 0.2), method="bounded").x)
    P_valid = goal_markets(valid_goals["lam"], valid_goals["mu"], rho)
    yv = targets(df)
    valid_ll = {t: _logloss(P_valid[t], yv[t][va]) for t in TASKS}
    models = {side: _new(params[side], n_iter[side], early=False).fit(X[tr | va], df[col].to_numpy(float)[tr | va])
              for side, col in SIDES.items()}
    return PoissonGoalModel(use_elo_dc, comps, params, {s: int(v) for s, v in n_iter.items()}, round(rho, 5),
                            valid_ll, models), P_valid


def refit_production(df: pd.DataFrame, m: PoissonGoalModel) -> PoissonGoalModel:
    """Modelo de producción: mismos hiperparámetros, árboles y rho elegidos en validación, reentrenado con TODOS los
    partidos terminados hasta hoy (incluido el período de prueba, ya evaluado)."""
    start = TRAIN_FROM if not m.use_elo_dc else "2016-01-01"
    rows = (df.kickoff_utc >= start).to_numpy().copy()
    if m.use_elo_dc:
        rows &= df[ELO_DC_COLS[0]].notna().to_numpy()
    X = design(df, m.use_elo_dc, m.comps)
    models = {side: _new(m.params[side], m.n_iter[side], early=False).fit(X[rows], df[col].to_numpy(float)[rows])
              for side, col in SIDES.items()}
    return PoissonGoalModel(m.use_elo_dc, m.comps, m.params, m.n_iter, m.rho, m.valid_logloss, models)


def save(model: PoissonGoalModel, meta: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ARTIFACTS / "model.joblib")
    (ARTIFACTS / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8",
                                          newline="\n")


def load() -> tuple[PoissonGoalModel, dict] | tuple[None, None]:
    path = ARTIFACTS / "model.joblib"
    if not path.exists():
        return None, None
    return joblib.load(path), json.loads((ARTIFACTS / "meta.json").read_text(encoding="utf-8"))


def blend_1x2(p_ml: np.ndarray, p_mkt: np.ndarray, w: list[float]) -> np.ndarray:
    from footy.models.ensemble import pool

    return pool([p_ml, p_mkt], np.asarray(w))


def blend_binary(p_ml, p_mkt, w: list[float]) -> np.ndarray:
    from footy.markets.combos import logit

    z = w[0] * logit(p_ml) + w[1] * logit(p_mkt) + w[2]
    return 1 / (1 + np.exp(-z))
