"""Modelo Dixon-Coles con ponderación temporal.

log(goles esperados del equipo i vs j) = intercepto + ataque_i - defensa_j (+ ventaja local)

Ajuste en dos pasos, rápido y estable:
1. Poisson GLM ponderado (sklearn PoissonRegressor) para ataques, defensas y localía.
   La regularización L2 (alpha) encoge a equipos con pocos datos hacia la media,
   lo que evita parámetros extremos para equipos recién ascendidos.
2. rho de Dixon-Coles por máxima verosimilitud en 1-D con las lambdas ya ajustadas.

Ponderación: peso = exp(-xi * días de antigüedad); xi = 0.002 -> vida media ~1 año.

Variante con tiros (mix < 1): el objetivo del GLM deja de ser solo goles y pasa a ser
    mix * goles + (1 - mix) * goles_esperados_por_tiros
donde goles_esperados_por_tiros = b_arco * tiros_al_arco + b_fuera * tiros_fuera, con b
estimados por mínimos cuadrados ponderados en la MISMA ventana de entrenamiento (sin leakage).
Los goles tienen mucho ruido; los tiros miden mejor la producción ofensiva subyacente.
Partidos sin estadísticas usan solo goles. rho siempre se ajusta con goles reales.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.linear_model import PoissonRegressor

from footy.markets.scoreline import outcome_probs, tau


class DixonColes:
    def __init__(self, xi: float = 0.002, alpha: float = 1e-3, window_days: int = 1095, mix: float = 1.0):
        self.xi = xi
        self.alpha = alpha
        self.window_days = window_days
        self.mix = mix

    def fit(self, df: pd.DataFrame, now: pd.Timestamp) -> "DixonColes":
        """df: partidos terminados ANTES de `now` (columnas home_id, away_id, home_goals, away_goals, kickoff)."""
        age = (now - df.kickoff).dt.total_seconds().to_numpy() / 86400
        keep = age <= self.window_days
        d = df[keep]
        w = np.exp(-self.xi * age[keep])

        teams = pd.Index(sorted(set(d.home_id) | set(d.away_id)))
        self.teams = {t: k for k, t in enumerate(teams)}
        X = self._design(d.home_id.to_numpy(), d.away_id.to_numpy())
        goals = np.concatenate([d.home_goals.to_numpy(), d.away_goals.to_numpy()]).astype(float)
        target = self._target(d, goals, np.tile(w, 2)) if self.mix < 1 else goals
        self.glm = PoissonRegressor(alpha=self.alpha, max_iter=1000).fit(X, target, sample_weight=np.tile(w, 2))

        lam, mu = self.expected_goals(d.home_id.to_numpy(), d.away_id.to_numpy())
        hg, ag = d.home_goals.to_numpy(), d.away_goals.to_numpy()
        low = (hg <= 1) & (ag <= 1)

        def nll(rho):
            t = tau(hg[low], ag[low], lam[low], mu[low], rho)
            return -np.sum(w[low] * np.log(np.clip(t, 1e-10, None)))

        self.rho = minimize_scalar(nll, bounds=(-0.25, 0.25), method="bounded").x
        return self

    def _target(self, d: pd.DataFrame, goals: np.ndarray, w: np.ndarray) -> np.ndarray:
        sot = np.concatenate([d.h_sot.to_numpy(), d.a_sot.to_numpy()]).astype(float)
        off = np.concatenate([d.h_shots.to_numpy(), d.a_shots.to_numpy()]).astype(float) - sot
        ok = ~(np.isnan(sot) | np.isnan(off)) & (off >= 0)
        if ok.sum() < 200:
            self.shot_coefs = None
            return goals
        A = np.stack([sot[ok], off[ok]], axis=1) * np.sqrt(w[ok])[:, None]
        self.shot_coefs = np.clip(np.linalg.lstsq(A, goals[ok] * np.sqrt(w[ok]), rcond=None)[0], 0, None)
        out = goals.copy()
        out[ok] = self.mix * goals[ok] + (1 - self.mix) * np.stack([sot[ok], off[ok]], axis=1) @ self.shot_coefs
        return out

    def _design(self, home: np.ndarray, away: np.ndarray) -> np.ndarray:
        """Dos filas por partido (goles local, goles visita). Columnas: [ataque | defensa | localía].

        Equipos desconocidos (sin partidos en la ventana) quedan en 0 = equipo promedio.
        """
        n, k = len(home), len(self.teams)
        X = np.zeros((2 * n, 2 * k + 1))
        hi = np.array([self.teams.get(t, -1) for t in home])
        ai = np.array([self.teams.get(t, -1) for t in away])
        rows = np.arange(n)
        for r_off, att, dfn in ((0, hi, ai), (n, ai, hi)):
            ok = att >= 0
            X[rows[ok] + r_off, att[ok]] = 1.0
            ok = dfn >= 0
            X[rows[ok] + r_off, k + dfn[ok]] = -1.0
        X[:n, -1] = 1.0
        return X

    def expected_goals(self, home: np.ndarray, away: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        pred = self.glm.predict(self._design(np.asarray(home), np.asarray(away)))
        n = len(home)
        return pred[:n], pred[n:]

    def predict(self, df: pd.DataFrame) -> dict:
        lam, mu = self.expected_goals(df.home_id.to_numpy(), df.away_id.to_numpy())
        return {"P": outcome_probs(lam, mu, self.rho), "lam": lam, "mu": mu}
