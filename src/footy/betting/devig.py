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


# Cuotas 1X2 dañadas: el calendario de football-data trae a veces precios de Betfair Exchange sin liquidez
# (p. ej. 1,31 / 3,35 / 1,31: margen 82%). En 780 capturas de 2026, el 21% tenía margen > 15%; las sanas nunca se
# alejan más de 0,043 del promedio del mercado y las dañadas 0,145 de media. Usarlas como referencia empeoraba el
# pronóstico oficial (log loss 1,043 vs 0,940 en vivo).
MIN_MARGIN, MAX_MARGIN = -0.03, 0.15
MAX_GAP = 0.08                # diferencia máxima de probabilidad con el promedio del mercado
CONSENSUS = "Market Avg"


def valid_1x2(odds) -> bool:
    """Tres cuotas > 1 con un margen posible (entre −3% y 15%)."""
    o = np.asarray(odds, dtype=float)
    return o.shape == (3,) and bool(np.all(o > 1)) and MIN_MARGIN <= float(np.sum(1 / o)) - 1 <= MAX_MARGIN


def clean_1x2(books: dict) -> dict:
    """Casas con cuotas 1X2 utilizables: margen posible y, si hay promedio de mercado, sin alejarse de él más de
    MAX_GAP en ninguna probabilidad. Se aplica antes de elegir la cuota de referencia."""
    ok = {b: np.asarray(o, dtype=float) for b, o in books.items() if valid_1x2(o)}
    if CONSENSUS not in ok:
        return ok
    ref = proportional(ok[CONSENSUS][None, :])[0]
    return {b: o for b, o in ok.items()
            if b == CONSENSUS or float(np.max(np.abs(proportional(o[None, :])[0] - ref))) <= MAX_GAP}
