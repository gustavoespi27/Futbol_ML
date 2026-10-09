"""Modelos de machine learning (gradient boosting) sobre el historial de los equipos.

Tareas: resultado 1X2 (multiclase), más de 2,5 goles y ambos marcan (binarias).
Variables: footy.features.history (forma, tiros, localía, temporada, rachas, descanso, enfrentamientos directos,
contexto de liga) + liga como categoría + (opcional) predicciones walk-forward de Elo y Dixon-Coles.

Períodos (por kickoff), sin mirar nunca el siguiente:
  TRAIN  2014-07 → 2023      ajuste
  VALID  2024 → 2025         elección de hiperparámetros, número de árboles y pesos de la mezcla con el mercado
  TEST   2026 →              evaluación única (el modelo final se reentrena con TRAIN + VALID)
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from footy import config
from footy.features.history import feature_columns

TRAIN_FROM, VALID_FROM, TEST_FROM = "2014-07-01", "2024-01-01", "2026-01-01"
ARTIFACTS = config.PROJECT_ROOT / "artifacts" / "ml"
ELO_DC_COLS = ["Elo_pH", "Elo_pD", "Elo_pA", "Dixon-Coles_pH", "Dixon-Coles_pD", "Dixon-Coles_pA", "lam", "mu"]
GRID = [{"learning_rate": lr, "max_leaf_nodes": leaves, "min_samples_leaf": leaf, "l2_regularization": 1.0}
        for lr in (0.04,) for leaves in (15, 31) for leaf in (200, 800)]
TASKS = {"1x2": 3, "over25": 2, "btts": 2}


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


def _proba(model, X) -> np.ndarray:
    P = model.predict_proba(X)
    return P if P.shape[1] > 2 else P[:, 1]


def _new(params: dict, max_iter: int, early: bool) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        **params, max_iter=max_iter, early_stopping=early, validation_fraction=0.1 if early else None,
        n_iter_no_change=30, categorical_features="from_dtype", random_state=0)


@dataclass
class TaskModel:
    task: str
    use_elo_dc: bool
    comps: list[str]
    params: dict
    n_iter: int
    valid_logloss: float
    model: HistGradientBoostingClassifier = field(repr=False, default=None)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return _proba(self.model, design(df, self.use_elo_dc, self.comps))


def fit_task(df: pd.DataFrame, task: str, use_elo_dc: bool, log=print) -> tuple[TaskModel, np.ndarray]:
    """Elige hiperparámetros en VALID, reentrena con TRAIN+VALID. Devuelve el modelo y sus predicciones de VALID
    (hechas con el modelo de solo TRAIN, para ajustar la mezcla con el mercado sin mirar el futuro)."""
    comps = sorted(df.comp.unique())
    y = targets(df)[task]
    k = df.kickoff_utc
    start = TRAIN_FROM if not use_elo_dc else "2016-01-01"
    tr = ((k >= start) & (k < VALID_FROM)).to_numpy()
    va = ((k >= VALID_FROM) & (k < TEST_FROM)).to_numpy()
    if use_elo_dc:
        has = df[ELO_DC_COLS[0]].notna().to_numpy()
        tr, va = tr & has, va & has
    X = design(df, use_elo_dc, comps)
    best = None
    for params in GRID:
        m = _new(params, 1000, early=True).fit(X[tr], y[tr])
        P = _proba(m, X[va])
        ll = _logloss(P, y[va])
        log(f"  {task} elo_dc={use_elo_dc} {params} árboles={m.n_iter_} logloss VALID={ll:.5f}")
        if best is None or ll < best[0]:
            best = (ll, params, m.n_iter_, P)
    ll, params, n_iter, P_valid = best
    final = _new(params, n_iter, early=False).fit(X[tr | va], y[tr | va])
    return TaskModel(task, use_elo_dc, comps, params, int(n_iter), ll, final), P_valid


def refit_production(df: pd.DataFrame, models: dict[str, TaskModel]) -> dict[str, TaskModel]:
    """Modelos de producción: mismos hiperparámetros y número de árboles elegidos en validación, reentrenados con
    TODOS los partidos terminados hasta hoy (incluido el período de prueba, ya evaluado)."""
    out = {}
    y_all = targets(df)
    for task, m in models.items():
        start = TRAIN_FROM if not m.use_elo_dc else "2016-01-01"
        rows = (df.kickoff_utc >= start).to_numpy().copy()
        if m.use_elo_dc:
            rows &= df[ELO_DC_COLS[0]].notna().to_numpy()
        X = design(df, m.use_elo_dc, m.comps)
        final = _new(m.params, m.n_iter, early=False).fit(X[rows], y_all[task][rows])
        out[task] = TaskModel(task, m.use_elo_dc, m.comps, m.params, m.n_iter, m.valid_logloss, final)
    return out


def save(models: dict[str, TaskModel], meta: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, ARTIFACTS / "models.joblib")
    (ARTIFACTS / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8",
                                          newline="\n")


def load() -> tuple[dict[str, TaskModel], dict] | tuple[None, None]:
    path = ARTIFACTS / "models.joblib"
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


def models_dir() -> Path:
    return ARTIFACTS
