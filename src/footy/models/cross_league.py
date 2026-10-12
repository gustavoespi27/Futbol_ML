"""Modelo entre ligas para las copas de clubes (Champions, Europa, Conference, Libertadores, Sudamericana).

El Elo de cada liga es un sistema cerrado: no sirve para comparar un club inglés con uno portugués. Aquí:
1. Elo global: un solo rating para todos los clubes, recorriendo todos los partidos de clubes en orden (las copas
   conectan las ligas entre sí).
2. Ajuste por liga: cada club suma el ajuste de su liga doméstica (la última liga que jugó; "OTHER" si no es una
   liga seguida). Los ajustes y el logit ordinal se estiman juntos por máxima verosimilitud con los cruces de copas,
   con penalización L2 hacia 0.

Validación walk-forward (docs/decisiones.md, 2026-10-11): entrenado con copas 2022-08 a 2024-06 y probado en
1.806 partidos de copa posteriores: log loss 0,970 contra 0,988 del Elo global solo y 1,038 del ingenuo.
"""

import pickle
import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from footy import config
from footy.models.elo import OrderedLogit, pre_match_ratings

CUPS = ("UCL", "UEL", "UECL", "LIB", "SUD")
K, HOME_ADV, L2 = 30, 80, 5.0               # elegidos en la validación (k=20/30, local 60/80, L2 1/5/20)
OTHER = "OTHER"                              # clubes de ligas que no seguimos
PATH = config.PROJECT_ROOT / "data" / "cache" / "cross_league.pkl"
VERSION = "cross_elo_v1"


def load_club_matches(conn: sqlite3.Connection) -> pd.DataFrame:
    """Partidos de clubes terminados (sin selecciones), en orden, con la liga doméstica de cada equipo antes del
    partido (sin mirar el futuro)."""
    df = pd.read_sql_query(
        """SELECT m.id AS match_id, c.code AS comp, c.type, m.kickoff_utc, m.home_team_id AS home_id,
                  m.away_team_id AS away_id, m.home_goals, m.away_goals
           FROM matches m JOIN competitions c ON c.id = m.competition_id
           WHERE m.status = 'finished' AND m.home_goals IS NOT NULL AND c.type != 'international'
           ORDER BY m.kickoff_utc, m.id""", conn)
    df["kickoff"] = pd.to_datetime(df.kickoff_utc, utc=True)
    df["y"] = np.where(df.home_goals > df.away_goals, 0, np.where(df.home_goals == df.away_goals, 1, 2))
    league_of: dict[int, str] = {}
    lh, la = [], []
    for r in df.itertuples(index=False):
        lh.append(league_of.get(r.home_id, OTHER))
        la.append(league_of.get(r.away_id, OTHER))
        if r.type == "league":
            league_of[r.home_id] = league_of[r.away_id] = r.comp
    df["lh"], df["la"] = lh, la
    df.attrs["league_of"] = league_of
    return df


def fit_offsets(x: np.ndarray, lh, la, y: np.ndarray, leagues: list[str], l2: float = L2) -> np.ndarray:
    """[c1, c2, b, ajuste por liga...] del logit ordinal con x = dif. Elo/400 + ajuste(local) - ajuste(visita)."""
    idx = {lg: i for i, lg in enumerate(leagues)}
    ih = np.array([idx[v] for v in lh])
    ia = np.array([idx[v] for v in la])

    def nll(p):
        off = p[3:]
        P = OrderedLogit._probs(x + off[ih] - off[ia], *p[:3])
        return -np.sum(np.log(np.clip(P[np.arange(len(y)), y], 1e-12, 1))) + l2 * np.sum(off ** 2)

    p0 = np.r_[OrderedLogit().fit(x * 400, y).params, np.zeros(len(leagues))]
    return minimize(nll, p0, method="L-BFGS-B").x


@dataclass
class CrossLeagueModel:
    ratings: dict[int, float]
    league_of: dict[int, str]
    params: np.ndarray
    leagues: list[str]
    n_train: int = 0
    offsets: dict[str, float] = field(default_factory=dict)

    def probabilities(self, home_id: int, away_id: int) -> np.ndarray:
        """P(local, empate, visita) con los ratings actuales. Un club sin historial parte de la media - 100."""
        default = float(np.mean(list(self.ratings.values()))) - 100
        d = self.ratings.get(home_id, default) + HOME_ADV - self.ratings.get(away_id, default)
        off = {lg: v / 400 for lg, v in self.offsets.items()}
        x = d / 400 + off.get(self.league_of.get(home_id, OTHER), 0) - off.get(self.league_of.get(away_id, OTHER), 0)
        return OrderedLogit._probs(np.array([x]), *self.params[:3])[0]


def fit(conn: sqlite3.Connection) -> CrossLeagueModel:
    df = load_club_matches(conn)
    diff, ratings = pre_match_ratings(df, k=K, home_adv=HOME_ADV, return_ratings=True)
    cup = df.comp.isin(CUPS).to_numpy()
    leagues = sorted(set(df.lh[cup]) | set(df.la[cup]) | {OTHER})
    params = fit_offsets(diff[cup] / 400, df.lh[cup], df.la[cup], df.y.to_numpy()[cup], leagues)
    return CrossLeagueModel(ratings=ratings, league_of=df.attrs["league_of"], params=params, leagues=leagues,
                            n_train=int(cup.sum()), offsets={lg: float(v * 400) for lg, v in zip(leagues, params[3:])})


def save(model: CrossLeagueModel) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_bytes(pickle.dumps(model))


def load() -> CrossLeagueModel | None:
    return pickle.loads(PATH.read_bytes()) if PATH.exists() else None
