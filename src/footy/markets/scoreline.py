"""De goles esperados (lambda local, mu visita) a probabilidades de todos los mercados.

Base: dos Poisson independientes con la corrección de Dixon-Coles (1997), que
ajusta la probabilidad de los marcadores bajos (0-0, 1-0, 0-1, 1-1) con un
parámetro rho. Todos los mercados salen de la MISMA matriz de marcadores, así
que son coherentes entre sí (1X2, Over/Under, BTTS, marcador exacto).
"""

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 10


def tau(x, y, lam, mu, rho):
    """Factor de corrección DC; vale 1 salvo en marcadores con ambos equipos <= 1."""
    t = np.ones(np.broadcast(x, y, lam).shape)
    t = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lam * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + mu * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


def score_matrix(lam: float, mu: float, rho: float = 0.0, max_goals: int = MAX_GOALS) -> np.ndarray:
    """M[i, j] = P(local marca i, visita marca j). Renormalizada para sumar 1."""
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
    m[:2, :2] *= tau(g[:2, None], g[None, :2], lam, mu, rho)
    return m / m.sum()


def score_matrices(lam: np.ndarray, mu: np.ndarray, rho: float = 0.0) -> np.ndarray:
    """score_matrix vectorizado para muchos partidos: (n, G, G), cada matriz renormalizada para sumar 1."""
    lam, mu = np.atleast_1d(lam), np.atleast_1d(mu)
    g = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(g[None, :], lam[:, None])           # (n, G)
    pa = poisson.pmf(g[None, :], mu[:, None])
    m = ph[:, :, None] * pa[:, None, :]                  # (n, G, G)
    m[:, :2, :2] *= tau(g[None, :2, None], g[None, None, :2], lam[:, None, None], mu[:, None, None], rho)
    return m / m.sum(axis=(1, 2), keepdims=True)


def outcome_probs(lam: np.ndarray, mu: np.ndarray, rho: float = 0.0) -> np.ndarray:
    """P(H, D, A) vectorizado para muchos partidos. Devuelve (n, 3)."""
    m = score_matrices(lam, mu, rho)
    home = np.tril(np.ones((MAX_GOALS + 1,) * 2), -1)    # i > j
    out = np.stack([(m * home).sum(axis=(1, 2)),
                    np.trace(m, axis1=1, axis2=2),
                    (m * home.T).sum(axis=(1, 2))], axis=1)
    return out


def markets(lam: float, mu: float, rho: float = 0.0, top_scores: int = 5) -> dict:
    """Todos los mercados de un partido a partir de su matriz de marcadores."""
    m = score_matrix(lam, mu, rho)
    g = np.arange(m.shape[0])
    total = g[:, None] + g[None, :]
    res = {
        "home": float(np.tril(m, -1).sum()),
        "draw": float(np.trace(m)),
        "away": float(np.triu(m, 1).sum()),
        "xg_home": lam,
        "xg_away": mu,
        "btts_yes": float(m[1:, 1:].sum()),
        "over_under": {line: float(m[total > line].sum()) for line in (0.5, 1.5, 2.5, 3.5, 4.5)},
    }
    res["btts_no"] = 1 - res["btts_yes"]
    flat = np.argsort(m, axis=None)[::-1][:top_scores]
    res["top_scores"] = [(f"{i}-{j}", float(m[i, j])) for i, j in zip(*np.unravel_index(flat, m.shape))]
    return res
