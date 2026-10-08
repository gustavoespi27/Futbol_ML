"""Métricas de evaluación probabilística para resultados 1X2.

Convención: y es un array de enteros 0=local, 1=empate, 2=visita; P es (n, 3)
con columnas en ese orden (el orden importa para el RPS).
"""

import numpy as np
import pandas as pd

EPS = 1e-15


def one_hot(y: np.ndarray, k: int = 3) -> np.ndarray:
    return np.eye(k)[np.asarray(y, dtype=int)]


def log_loss(y: np.ndarray, P: np.ndarray) -> float:
    p = np.clip(P[np.arange(len(y)), y], EPS, 1.0)
    return float(-np.mean(np.log(p)))


def brier(y: np.ndarray, P: np.ndarray) -> float:
    """Brier multiclase: suma sobre las clases, promedio sobre partidos (rango 0-2)."""
    return float(np.mean(((P - one_hot(y, P.shape[1])) ** 2).sum(axis=1)))


def rps(y: np.ndarray, P: np.ndarray) -> float:
    """Ranked Probability Score: penaliza más errar por dos categorías (local vs visita)."""
    cum_p = np.cumsum(P, axis=1)[:, :-1]
    cum_o = np.cumsum(one_hot(y, P.shape[1]), axis=1)[:, :-1]
    return float(np.mean(((cum_p - cum_o) ** 2).sum(axis=1) / (P.shape[1] - 1)))


def accuracy(y: np.ndarray, P: np.ndarray) -> float:
    return float(np.mean(P.argmax(axis=1) == y))


def summary(y: np.ndarray, P: np.ndarray) -> dict:
    return {"n": len(y), "log_loss": log_loss(y, P), "rps": rps(y, P),
            "brier": brier(y, P), "accuracy": accuracy(y, P)}


def calibration_table(p: np.ndarray, outcome: np.ndarray, bins=10) -> pd.DataFrame:
    """Probabilidad predicha media vs frecuencia observada por bin, con IC 95% de Wilson."""
    edges = np.linspace(0, 1, bins + 1) if np.isscalar(bins) else np.asarray(bins)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, len(edges) - 2)
    rows = []
    for b in range(len(edges) - 1):
        m = idx == b
        n = int(m.sum())
        if n == 0:
            continue
        freq = outcome[m].mean()
        lo, hi = wilson(freq, n)
        rows.append({"bin_lo": edges[b], "bin_hi": edges[b + 1], "n": n,
                     "pred": p[m].mean(), "obs": freq, "obs_lo": lo, "obs_hi": hi})
    return pd.DataFrame(rows)


def ece(p: np.ndarray, outcome: np.ndarray, bins: int = 10) -> float:
    """Expected Calibration Error: |pred - obs| promedio ponderado por tamaño del bin."""
    t = calibration_table(p, outcome, bins)
    return float((t["n"] * (t["pred"] - t["obs"]).abs()).sum() / t["n"].sum())


def wilson(freq: float, n: int, z: float = 1.96) -> tuple[float, float]:
    denom = 1 + z ** 2 / n
    center = (freq + z ** 2 / (2 * n)) / denom
    half = z * np.sqrt(freq * (1 - freq) / n + z ** 2 / (4 * n ** 2)) / denom
    return center - half, center + half


def bootstrap_mean_ci(x: np.ndarray, n_boot: int = 2000, alpha: float = 0.05,
                      seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    means = rng.choice(x, size=(n_boot, len(x)), replace=True).mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))
