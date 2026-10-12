"""Predicciones del modelo de machine learning para los partidos programados.

Calcular las variables del historial recorre toda la base (~1 minuto), así que el resultado se guarda en
data/processed/ml/upcoming.pkl; lo recalcula la tarea diaria o, si falta o es muy antiguo, la primera consulta.
"""

import time

import numpy as np
import pandas as pd

from footy import config
from footy.db.connection import connect
from footy.features.history import build_features, load_all_matches
from footy.leagues import load_params
from footy.models import ml

CACHE = config.path("processed") / "ml" / "upcoming.pkl"
MAX_AGE = 26 * 3600          # la tarea diaria lo recalcula dos veces al día
STAT_FEATURES = ("pts_5", "gf_10", "ga_10", "sf_10", "sa_10", "tf_10", "venue_pts5", "season_ppg", "season_gd",
                 "season_n", "rest", "unbeaten", "winless")


def compute(days_ahead: int = 10) -> pd.DataFrame:
    model, _ = ml.load()
    if model is None:
        return pd.DataFrame()
    conn = connect()
    df = build_features(load_all_matches(conn))
    now = pd.Timestamp.now(tz="UTC")
    up = df[(df.status == "scheduled") & (df.kickoff > now) & (df.kickoff < now + pd.Timedelta(days=days_ahead))]
    up = up.reset_index(drop=True)
    for c in ml.ELO_DC_COLS:
        up[c] = np.nan
    params = load_params()
    from footy.web.service import predictor  # predictores cacheados del dashboard

    for code, idx in up.groupby("comp").groups.items():
        if code not in params:
            continue
        try:
            pred = predictor(code)
        except Exception:  # noqa: BLE001 - sin predictor la variante sin Elo/DC sigue funcionando (NaN)
            continue
        for i in idx:
            try:
                comp = pred.components(int(up.at[i, "home_id"]), int(up.at[i, "away_id"]))
            except Exception:  # noqa: BLE001
                continue
            for k, v in comp.items():
                up.at[i, k] = v
    out = pd.DataFrame({"match_id": up.match_id})
    lam, mu = model.goals(up) if len(up) else (np.array([]), np.array([]))
    P = ml.goal_markets(lam, mu, model.rho) if len(up) else {t: np.empty((0, 3) if t == "1x2" else 0) for t in ml.TASKS}
    out[["ml_H", "ml_D", "ml_A"]] = P["1x2"]
    out["ml_over25"], out["ml_btts"] = P["over25"], P["btts"]
    # Competiciones que el modelo no vio al entrenar (selecciones, copas internacionales): sin pronóstico ML.
    unseen = ~up.comp.isin(model.comps).to_numpy()
    out.loc[unseen, ["ml_H", "ml_D", "ml_A", "ml_over25", "ml_btts"]] = np.nan
    # Estadísticas previas para mostrar en el dashboard (las mismas variables que usa el modelo, de partidos ya
    # jugados): también en competiciones que el modelo no vio, porque salen del historial de cada equipo.
    for side in ("h", "a"):
        for f in STAT_FEATURES:
            out[f"st_{side}_{f}"] = up[f"{side}_{f}"].to_numpy()
    for f in ("h2h_n", "h2h_pts", "h2h_gd"):
        out[f"st_{f}"] = up[f].to_numpy()
    return out


def upcoming(refresh: bool = False) -> pd.DataFrame:
    """Predicciones ML de los partidos programados, indexadas por match_id (vacío si no hay modelos entrenados)."""
    fresh = CACHE.exists() and time.time() - CACHE.stat().st_mtime < MAX_AGE
    if fresh and not refresh:
        return pd.read_pickle(CACHE)
    out = compute()
    if not out.empty:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        out = out.set_index("match_id")
        out.to_pickle(CACHE)
    return out
