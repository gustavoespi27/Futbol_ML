"""Combinación log-lineal de probabilidades: P ∝ Π P_i ^ w_i.

Los pesos se ajustan minimizando log loss en un período de VALIDACIÓN y se
aplican sin cambios al período de test. Incluir el mercado como una de las
fuentes responde la pregunta clave: ¿el modelo aporta información que el
mercado no tiene? (peso del modelo > 0 y mejor log loss que el mercado solo).
"""

import numpy as np
from scipy.optimize import minimize


def pool(Ps: list[np.ndarray], w: np.ndarray) -> np.ndarray:
    logp = sum(wi * np.log(np.clip(P, 1e-12, 1)) for wi, P in zip(w, Ps))
    logp -= logp.max(axis=1, keepdims=True)
    e = np.exp(logp)
    return e / e.sum(axis=1, keepdims=True)


def fit_weights(Ps: list[np.ndarray], y: np.ndarray, nonneg: bool = False) -> np.ndarray:
    """Con nonneg=True los pesos quedan >= 0: un peso negativo "invierte" una fuente y
    extrapola mal fuera de validación (ver docs/decisiones.md, 2026-10-09)."""
    def nll(w):
        P = pool(Ps, w)
        return -np.mean(np.log(np.clip(P[np.arange(len(y)), y], 1e-12, 1)))

    x0 = np.full(len(Ps), 1.0 / len(Ps))
    if nonneg:
        return minimize(nll, x0, method="L-BFGS-B", bounds=[(0, 3)] * len(Ps)).x
    return minimize(nll, x0, method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-5}).x
