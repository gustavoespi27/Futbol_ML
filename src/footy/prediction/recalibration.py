"""Ajuste automático de las probabilidades con los resultados reales (recalibración por temperatura).

Si el sistema resulta demasiado seguro (dice 70% y ocurre 60%) o demasiado tímido, se corrige con una temperatura T:
    p_i ∝ p_i ** (1 / T)        T > 1 suaviza (menos seguro), T < 1 agudiza (más seguro).
T se ajusta minimizando el log loss de las predicciones registradas ANTES de cada partido (seguimiento prospectivo)
y se encoge hacia 1 según la cantidad de datos: T_ef = 1 + (T − 1) · n / (n + N0). Con pocos partidos el ajuste es
casi nulo y crece poco a poco. Lo recalcula la tarea diaria; el historial queda en data/processed/calibration.json.
"""

import json
import sqlite3
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize_scalar

from footy import config

PATH = config.path("processed") / "calibration.json"
N0 = 300                 # partidos que hacen falta para confiar la mitad en el ajuste
BOUNDS = (0.80, 1.25)    # límites prudentes al ajuste efectivo


def scale(p, T: float):
    """Aplica la temperatura a probabilidades 1X2 (una fila o varias)."""
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1)
    if abs(T - 1) < 1e-9:
        return p / p.sum(axis=-1, keepdims=True)
    q = p ** (1 / T)
    return q / q.sum(axis=-1, keepdims=True)


def _ll(P, y):
    return float(-np.mean(np.log(P[np.arange(len(y)), y])))


def fit(P: np.ndarray, y: np.ndarray) -> dict:
    n = len(y)
    if n < 10:
        return {"T": 1.0, "T_fit": 1.0, "n": n, "ll_before": None, "ll_after": None}
    res = minimize_scalar(lambda t: _ll(scale(P, t), y), bounds=(0.5, 2.0), method="bounded")
    T_fit = float(res.x)
    T = float(np.clip(1 + (T_fit - 1) * n / (n + N0), *BOUNDS))
    return {"T": round(T, 4), "T_fit": round(T_fit, 4), "n": n,
            "ll_before": round(_ll(scale(P, 1.0), y), 5), "ll_after": round(_ll(scale(P, T), y), 5)}


def update(conn: sqlite3.Connection) -> dict:
    """Reajusta con todo el seguimiento liquidado y guarda el historial (lo llama scripts/daily.py)."""
    from footy.prediction import tracking

    matches, _ = tracking.evaluate(conn, tracking.ALL_VERSIONS)
    if matches.empty:
        P, y = np.empty((0, 3)), np.empty(0, dtype=int)
    else:
        m = matches.sort_values("kickoff").groupby("match_id").tail(1)       # una predicción por partido
        P, y = np.array(m.p_official.tolist(), dtype=float), m.y.to_numpy(int)
    r = fit(P, y)
    hist = load().get("history", [])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hist = [h for h in hist if h["date"] != today] + [{"date": today, **r}]
    out = {**r, "updated": today, "history": hist[-180:]}
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    return r


def load() -> dict:
    if PATH.exists():
        return json.loads(PATH.read_text(encoding="utf-8"))
    return {"T": 1.0, "n": 0, "history": []}


def current_T() -> float:
    return float(load().get("T", 1.0))
