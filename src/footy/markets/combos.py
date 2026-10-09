"""Selecciones y combinadas a partir de la matriz de marcadores de un partido.

Cada selección (gana local, más de 2,5 goles, ambos marcan, ...) es un conjunto de marcadores, así que:
- la probabilidad de VARIAS selecciones del MISMO partido es la suma de la matriz sobre la intersección
  (exacta, respeta la correlación: "local + más de 2,5" no es el producto de ambas);
- partidos distintos se tratan como independientes: la probabilidad de la combinada es el producto.

La matriz de Dixon-Coles se ajusta (IPF) para que sus marginales 1X2 y Over/Under 2,5 coincidan con las
probabilidades oficiales (modelo + mercado), sin perder la forma de la distribución de goles.
"""

from itertools import combinations

import numpy as np

from footy.markets.scoreline import MAX_GOALS, score_matrix

_G = np.arange(MAX_GOALS + 1)
_H, _A = np.meshgrid(_G, _G, indexing="ij")
_T = _H + _A

# clave -> (etiqueta, grupo, máscara sobre la matriz [goles local, goles visita])
SELECTIONS: dict[str, tuple[str, str, np.ndarray]] = {
    "1": ("Gana local", "Resultado", _H > _A),
    "X": ("Empate", "Resultado", _H == _A),
    "2": ("Gana visita", "Resultado", _H < _A),
    "1X": ("Local o empate", "Doble oportunidad", _H >= _A),
    "X2": ("Empate o visita", "Doble oportunidad", _H <= _A),
    "12": ("Local o visita (sin empate)", "Doble oportunidad", _H != _A),
    "O1.5": ("Más de 1,5 goles", "Goles", _T > 1.5),
    "U1.5": ("Menos de 1,5 goles", "Goles", _T < 1.5),
    "O2.5": ("Más de 2,5 goles", "Goles", _T > 2.5),
    "U2.5": ("Menos de 2,5 goles", "Goles", _T < 2.5),
    "O3.5": ("Más de 3,5 goles", "Goles", _T > 3.5),
    "U3.5": ("Menos de 3,5 goles", "Goles", _T < 3.5),
    "BTTS_Y": ("Ambos marcan: sí", "Ambos marcan", (_H > 0) & (_A > 0)),
    "BTTS_N": ("Ambos marcan: no", "Ambos marcan", (_H == 0) | (_A == 0)),
}
# Grupos que pueden combinarse dentro del mismo partido (dos del mismo grupo son redundantes o imposibles).
RESULT_GROUPS = ("Resultado", "Doble oportunidad")
GOAL_GROUPS = ("Goles", "Ambos marcan")


def label(keys: list[str]) -> str:
    return " + ".join(SELECTIONS[k][0] for k in keys)


def fit_matrix(lam: float, mu: float, rho: float = 0.0, p1x2=None, p_over25: float | None = None,
               iters: int = 30, p_btts: float | None = None) -> np.ndarray:
    """Matriz de marcadores con marginales 1X2, Over 2,5 (y ambos marcan) iguales a las dadas
    (ajuste proporcional iterativo)."""
    m = score_matrix(lam, mu, rho)
    if p1x2 is None and p_over25 is None and p_btts is None:
        return m
    res = [SELECTIONS[k][2] for k in "1X2"]
    tot = [_T > 2.5, _T < 2.5]
    btts = [SELECTIONS["BTTS_Y"][2], SELECTIONS["BTTS_N"][2]]
    for _ in range(iters):
        if p_btts is not None:
            for mask, target in zip(btts, (p_btts, 1 - p_btts)):
                s = m[mask].sum()
                if s > 0:
                    m[mask] *= target / s
        if p1x2 is not None:
            for mask, target in zip(res, p1x2):
                s = m[mask].sum()
                if s > 0:
                    m[mask] *= target / s
        if p_over25 is not None:
            for mask, target in zip(tot, (p_over25, 1 - p_over25)):
                s = m[mask].sum()
                if s > 0:
                    m[mask] *= target / s
    return m / m.sum()


def prob(m: np.ndarray, keys: list[str]) -> float:
    """Probabilidad de que se cumplan TODAS las selecciones (mismo partido)."""
    mask = np.ones_like(m, dtype=bool)
    for k in keys:
        mask &= SELECTIONS[k][2]
    return float(m[mask].sum())


def options(m: np.ndarray) -> list[dict]:
    return [{"key": k, "label": lab, "group": grp, "p": round(prob(m, [k]), 4)}
            for k, (lab, grp, _) in SELECTIONS.items()]


def suggestions(m: np.ndarray, top: int = 6, p_min: float = 0.25, p_max: float = 0.85) -> list[dict]:
    """Variantes de un mismo partido (resultado + goles) ordenadas por probabilidad.

    Se excluyen las casi seguras (> p_max: pagan poco y no aportan) y las muy improbables (< p_min)."""
    res = [k for k, v in SELECTIONS.items() if v[1] in RESULT_GROUPS]
    goals = [k for k, v in SELECTIONS.items() if v[1] in GOAL_GROUPS]
    pairs = [[r, g] for r in res for g in goals]
    pairs += [[a, b] for a, b in combinations(goals, 2) if SELECTIONS[a][1] != SELECTIONS[b][1]]
    out = []
    for keys in pairs:
        p = prob(m, keys)
        if p_min <= p <= p_max and p < min(prob(m, [k]) for k in keys) - 0.02:   # que no sea redundante
            out.append({"keys": keys, "label": label(keys), "p": round(p, 4)})
    return sorted(out, key=lambda r: -r["p"])[:top]


def pattern_hits(home_goals: int, away_goals: int, keys: list[str]) -> bool:
    h, a = min(home_goals, MAX_GOALS), min(away_goals, MAX_GOALS)
    return all(bool(SELECTIONS[k][2][h, a]) for k in keys)


def combo_odds(odds: list[float | None]) -> float | None:
    """Cuota de una combinada entre partidos distintos = producto de las cuotas (como la calculan las casas)."""
    if not odds or any(o is None for o in odds):
        return None
    return float(np.prod(odds))


def over_prob(lam: np.ndarray, mu: np.ndarray, rho: float = 0.0, line: float = 2.5) -> np.ndarray:
    """P(goles totales > line) de Dixon-Coles, vectorizado para muchos partidos."""
    from scipy.stats import poisson

    from footy.markets.scoreline import tau

    lam, mu = np.atleast_1d(lam), np.atleast_1d(mu)
    m = poisson.pmf(_G[None, :], lam[:, None])[:, :, None] * poisson.pmf(_G[None, :], mu[:, None])[:, None, :]
    m[:, :2, :2] *= tau(_G[None, :2, None], _G[None, None, :2], lam[:, None, None], mu[:, None, None], rho)
    return (m * (_T > line)).sum(axis=(1, 2)) / m.sum(axis=(1, 2))


def logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def calibrate_over(p_dc, p_market=None, params: dict | None = None) -> np.ndarray:
    """Probabilidad oficial de Over 2,5: combinación logística del modelo y el mercado (pesos de validación).
    params = {"dc": [a, c], "blend": [a, b, c]}; sin params devuelve el modelo tal cual."""
    if not params:
        return np.asarray(p_dc, dtype=float)
    if p_market is not None and not np.isnan(p_market).all():
        a, b, c = params["blend"]
        z = a * logit(p_dc) + b * logit(p_market) + c
    else:
        a, c = params["dc"]
        z = a * logit(p_dc) + c
    return 1 / (1 + np.exp(-z))


def implied_goals(p1x2, p_over25: float | None = None) -> tuple[float, float]:
    """Goles esperados (local, visita) cuyas Poisson reproducen mejor las probabilidades del mercado.
    Sirve para ligas sin modelo validado: la matriz resultante se ajusta luego con fit_matrix."""
    from scipy.optimize import minimize

    target = np.asarray(p1x2, dtype=float)

    def loss(x):
        lam, mu = np.exp(x)
        m = score_matrix(lam, mu)
        err = sum((m[SELECTIONS[k][2]].sum() - t) ** 2 for k, t in zip("1X2", target))
        if p_over25 is not None:
            err += (m[_T > 2.5].sum() - p_over25) ** 2
        return err

    x = minimize(loss, np.log([1.4, 1.1]), method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-9}).x
    lam, mu = np.exp(x)
    return float(lam), float(mu)
