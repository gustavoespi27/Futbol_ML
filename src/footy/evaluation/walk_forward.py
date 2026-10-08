"""Validación walk-forward: simula usar el modelo en tiempo real.

Para cada semana [t, t+7d): el modelo se ajusta SOLO con partidos con kickoff < t
y predice los partidos de esa semana. Luego t avanza 7 días. Nunca hay
información de la semana que se predice (ni posterior) en el ajuste.
"""

import numpy as np
import pandas as pd

from footy.models.dixon_coles import DixonColes
from footy.models.elo import OrderedLogit, pre_match_ratings

WEEK = pd.Timedelta(days=7)


def _weeks(df: pd.DataFrame, mask: np.ndarray):
    """Lunes 00:00 UTC de cada semana que contiene partidos a predecir."""
    starts = df.kickoff[mask].dt.normalize() - pd.to_timedelta(df.kickoff[mask].dt.weekday, unit="D")
    return sorted(starts.unique())


def walk_forward_dc(df: pd.DataFrame, mask: np.ndarray, **params) -> pd.DataFrame:
    """Predicciones Dixon-Coles para las filas de `mask`. df debe incluir todo el historial previo."""
    out = []
    for ws in _weeks(df, mask):
        block = mask & (df.kickoff >= ws).to_numpy() & (df.kickoff < ws + WEEK).to_numpy()
        train = df[df.kickoff < ws]
        model = DixonColes(**params).fit(train, ws)
        pred = model.predict(df[block])
        out.append(pd.DataFrame({"match_id": df.match_id[block].to_numpy(),
                                 "pH": pred["P"][:, 0], "pD": pred["P"][:, 1], "pA": pred["P"][:, 2],
                                 "lam": pred["lam"], "mu": pred["mu"], "rho": model.rho}))
    return pd.concat(out, ignore_index=True)


def walk_forward_elo(df: pd.DataFrame, mask: np.ndarray, refit_days: int = 28,
                     logit_years: float = 4, **elo_params) -> pd.DataFrame:
    """Predicciones Elo + logit ordinal. Los ratings son pre-partido por construcción;
    el logit se reajusta cada `refit_days` con los partidos anteriores al bloque."""
    diff = pre_match_ratings(df, **elo_params)
    out, logit, last_fit = [], None, None
    for ws in _weeks(df, mask):
        if logit is None or (ws - last_fit).days >= refit_days:
            hist = (df.kickoff < ws).to_numpy() & (df.kickoff >= ws - pd.Timedelta(days=365 * logit_years)).to_numpy()
            logit, last_fit = OrderedLogit().fit(diff[hist], df.y.to_numpy()[hist]), ws
        block = mask & (df.kickoff >= ws).to_numpy() & (df.kickoff < ws + WEEK).to_numpy()
        P = logit.predict(diff[block])
        out.append(pd.DataFrame({"match_id": df.match_id[block].to_numpy(),
                                 "pH": P[:, 0], "pD": P[:, 1], "pA": P[:, 2], "elo_diff": diff[block]}))
    return pd.concat(out, ignore_index=True)


def naive_frequencies(df: pd.DataFrame) -> np.ndarray:
    """Frecuencias H/D/A de la competición con partidos de días ANTERIORES (Laplace +1)."""
    out = np.full((len(df), 3), np.nan)
    for _, g in df.groupby("comp"):
        day = g.kickoff.dt.strftime("%Y-%m-%d")
        counts = pd.get_dummies(g.y).reindex(columns=[0, 1, 2], fill_value=0).astype(float)
        prior = counts.groupby(day.to_numpy()).sum().cumsum().shift(1).fillna(0) + 1.0
        vals = prior.loc[day].to_numpy()
        out[g.index] = vals / vals.sum(axis=1, keepdims=True)
    return out


def probs(pred: pd.DataFrame) -> np.ndarray:
    return pred[["pH", "pD", "pA"]].to_numpy()
