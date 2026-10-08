"""Elo para clubes + logit ordinal para convertir diferencia de rating en P(H, D, A).

Ratings: actualización estilo World Football Elo, con multiplicador por diferencia
de goles, ventaja local en puntos Elo, regresión a la media tras un parón largo
(> OFFSEASON_DAYS sin jugar, es decir, entre temporadas; funciona igual con
calendarios europeos, anuales o torneos cortos) y un rating inicial más bajo para
equipos nuevos (normalmente recién ascendidos).

`pre_match_ratings` recorre los partidos en orden y devuelve, para cada uno, la
diferencia de rating ANTES de jugarse (los partidos del mismo día no se ven entre sí).
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

OFFSEASON_DAYS = 45


def goal_multiplier(gd: np.ndarray) -> np.ndarray:
    gd = np.abs(gd)
    return np.where(gd <= 1, 1.0, np.where(gd == 2, 1.5, (11 + gd) / 8))


def pre_match_ratings(df: pd.DataFrame, k: float = 20, home_adv: float = 60,
                      new_team_offset: float = 100, season_regress: float = 0.2) -> np.ndarray:
    """Devuelve elo_diff = (R_local + ventaja local) - R_visita antes de cada partido."""
    ratings: dict[int, float] = {}
    last_played: dict[int, object] = {}
    diff = np.empty(len(df))
    dates = df.kickoff.dt.date.to_numpy()
    home, away = df.home_id.to_numpy(), df.away_id.to_numpy()
    hg, ag = df.home_goals.to_numpy(), df.away_goals.to_numpy()

    def active_mean(day):
        # Media de equipos que jugaron en el último año: los descendidos hace tiempo no cuentan.
        act = [r for t, r in ratings.items() if (day - last_played[t]).days <= 365]
        return float(np.mean(act)) if act else 1500.0

    def rating(team, day):
        if team not in ratings:
            ratings[team] = active_mean(day) - new_team_offset
        elif (day - last_played[team]).days > OFFSEASON_DAYS:
            ratings[team] += season_regress * (active_mean(day) - ratings[team])
        last_played[team] = day
        return ratings[team]

    i = 0
    n = len(df)
    while i < n:
        j = i
        while j < n and dates[j] == dates[i]:
            j += 1
        updates = []
        for m in range(i, j):
            rh, ra = rating(home[m], dates[m]), rating(away[m], dates[m])
            d = rh + home_adv - ra
            diff[m] = d
            expected = 1 / (1 + 10 ** (-d / 400))
            result = 1.0 if hg[m] > ag[m] else 0.5 if hg[m] == ag[m] else 0.0
            delta = k * goal_multiplier(hg[m] - ag[m]) * (result - expected)
            updates.append((home[m], delta))
            updates.append((away[m], -delta))
        for team, delta in updates:      # se aplican al terminar el día
            ratings[team] += delta
        i = j
    return diff


class OrderedLogit:
    """P(A) = s(c1 - b x); P(A o D) = s(c2 - b x), con c2 > c1. x = elo_diff / 400."""

    def fit(self, x: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> "OrderedLogit":
        x = np.asarray(x) / 400
        w = np.ones(len(x)) if w is None else w

        def nll(params):
            P = self._probs(x, *params)
            return -np.sum(w * np.log(np.clip(P[np.arange(len(y)), y], 1e-12, 1)))

        res = minimize(nll, x0=[-0.6, 0.6, 1.5], method="Nelder-Mead", options={"maxiter": 2000})
        self.params = res.x
        return self

    @staticmethod
    def _probs(x, c1, c2, b):
        lo, hi = min(c1, c2), max(c1, c2)
        p_a = expit(lo - b * x)
        p_ad = expit(hi - b * x)
        return np.stack([1 - p_ad, p_ad - p_a, p_a], axis=1)

    def predict(self, elo_diff: np.ndarray) -> np.ndarray:
        return self._probs(np.asarray(elo_diff) / 400, *self.params)
