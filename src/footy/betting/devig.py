"""Conversión de cuotas a probabilidades sin margen de la casa.

1/cuota sobreestima la probabilidad: las tres implícitas de un 1X2 suman más de 1
(el exceso es el margen u overround). Cada método reparte ese margen de forma distinta:

- proportional: divide por la suma. Simple; asigna margen proporcional a cada resultado.
- power: p_i = (1/o_i)^k con k tal que sum p_i = 1. Carga más margen en las cuotas
  largas, coherente con el sesgo favorito-longshot.
- shin: modelo de Shin (1993) con fracción z de apostadores informados.

Todas las funciones reciben un array (n, k) de cuotas decimales y devuelven (n, k).
"""

import numpy as np
from scipy.optimize import brentq


def implied(odds: np.ndarray) -> np.ndarray:
    return 1.0 / np.asarray(odds, dtype=float)


def overround(odds: np.ndarray) -> np.ndarray:
    """Margen de la casa: sum(1/o) - 1."""
    return implied(odds).sum(axis=1) - 1.0


def proportional(odds: np.ndarray) -> np.ndarray:
    q = implied(odds)
    return q / q.sum(axis=1, keepdims=True)


def power(odds: np.ndarray) -> np.ndarray:
    q = implied(odds)
    out = np.empty_like(q)
    for i, row in enumerate(q):
        k = brentq(lambda k: (row ** k).sum() - 1.0, 0.5, 3.0)
        out[i] = row ** k
    return out


def shin(odds: np.ndarray) -> np.ndarray:
    q = implied(odds)
    out = np.empty_like(q)
    for i, row in enumerate(q):
        b = row.sum()

        def probs(z):
            return (np.sqrt(z ** 2 + 4 * (1 - z) * row ** 2 / b) - z) / (2 * (1 - z))

        if b <= 1.0:
            out[i] = row / b
            continue
        z = brentq(lambda z: probs(z).sum() - 1.0, 0.0, 0.5)
        out[i] = probs(z)
    return out


METHODS = {"proportional": proportional, "power": power, "shin": shin}


def devig(odds: np.ndarray, method: str = "proportional") -> np.ndarray:
    return METHODS[method](odds)
