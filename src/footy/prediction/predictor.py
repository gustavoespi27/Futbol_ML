"""Predicción de partidos futuros con los modelos validados de una liga.

Ajusta Elo, logit ordinal y Dixon-Coles con TODOS los partidos terminados antes
de `now` y combina con los pesos elegidos en validación. Las probabilidades 1X2
salen del ensamble Elo+DC; goles esperados, Over/Under, BTTS y marcadores salen
de la matriz de Dixon-Coles.

Con cuotas: se quita el margen, se combina con el mercado (pesos de validación)
y se recomienda apostar SOLO si el EV supera el umbral elegido en validación.
Por defecto: NO APOSTAR.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from footy.betting.devig import overround, proportional
from footy.data import load_matches
from footy.db.connection import connect
from footy.db.repository import normalize_name
from footy.leagues import family, league_name, load_params
from footy.markets.scoreline import markets, outcome_probs
from footy.models.dixon_coles import DixonColes
from footy.models.elo import OrderedLogit, pre_match_ratings
from footy.models.ensemble import pool

LOGIT_YEARS = 4


@dataclass
class Team:
    id: int
    name: str


class LeaguePredictor:
    def __init__(self, code: str, now: pd.Timestamp | None = None, conn=None):
        self.code = code
        self.name = league_name(code)
        self.params = load_params()[code]
        self.now = now or pd.Timestamp.now(tz="UTC")
        conn = conn or connect()
        elo_comps, dc_comps = family(code)
        df = load_matches(conn, elo_comps, with_stats=True)
        df = df[df.kickoff < self.now].reset_index(drop=True)
        self.df = df

        elo_p = self.params["elo"]
        diff, self.ratings = pre_match_ratings(df, **elo_p, return_ratings=True)
        self.home_adv, self.new_offset = elo_p["home_adv"], elo_p["new_team_offset"]
        recent = (df.kickoff >= self.now - pd.Timedelta(days=365 * LOGIT_YEARS)).to_numpy()
        self.logit = OrderedLogit().fit(diff[recent], df.y.to_numpy()[recent])

        dc_df = df[df.comp.isin(dc_comps)]
        self.dc = DixonColes(**self.params["dixon_coles"]).fit(dc_df, self.now)
        last_year = dc_df[dc_df.kickoff >= self.now - pd.Timedelta(days=365)]
        self.recent_counts = pd.concat([last_year.home_id, last_year.away_id]).value_counts()
        self.teams = (pd.concat([dc_df[["home_id", "home"]].set_axis(["id", "name"], axis=1),
                                 dc_df[["away_id", "away"]].set_axis(["id", "name"], axis=1)])
                      .drop_duplicates("id").set_index("id").name)

    # --- equipos -----------------------------------------------------------

    def find_team(self, name: str) -> Team:
        target = normalize_name(name)
        exact = [i for i, n in self.teams.items() if normalize_name(n) == target]
        if exact:
            return Team(exact[0], self.teams[exact[0]])
        partial = [i for i, n in self.teams.items() if target in normalize_name(n)]
        if len(partial) == 1:
            return Team(partial[0], self.teams[partial[0]])
        import difflib
        sug = difflib.get_close_matches(name, list(self.teams.values), n=5, cutoff=0.3)
        raise KeyError(f"Equipo '{name}' no encontrado en {self.code}. ¿Quisiste decir: {', '.join(sug)}?")

    # --- predicción --------------------------------------------------------

    def _elo_diff(self, home: int, away: int) -> float:
        active = [r for r in self.ratings.values()]
        default = float(np.mean(active)) - self.new_offset
        return self.ratings.get(home, default) + self.home_adv - self.ratings.get(away, default)

    def predict(self, home: Team, away: Team, odds: tuple[float, float, float] | None = None) -> dict:
        p_elo = self.logit.predict(np.array([self._elo_diff(home.id, away.id)]))
        lam, mu = self.dc.expected_goals(np.array([home.id]), np.array([away.id]))
        p_dc = outcome_probs(lam, mu, self.dc.rho)
        p_model = pool([p_elo, p_dc], np.array(self.params["w_models"]))[0]
        out = {
            "league": self.code, "league_name": self.name, "home": home.name, "away": away.name,
            "p_model": p_model, "p_elo": p_elo[0], "p_dc": p_dc[0],
            "markets": markets(float(lam[0]), float(mu[0]), self.dc.rho),
            "confidence": self._confidence(home.id, away.id, p_elo[0], p_dc[0]),
            "status": self.params.get("status", "sin ventaja demostrada"),
        }
        if odds is not None:
            out["betting"] = self._betting(np.array(odds, dtype=float), p_elo, p_dc, p_model)
        return out

    def components(self, home: int, away: int) -> dict:
        """Piezas de Elo y Dixon-Coles con los mismos nombres que las columnas walk-forward (variables del ML)."""
        p_elo = self.logit.predict(np.array([self._elo_diff(home, away)]))[0]
        lam, mu = self.dc.expected_goals(np.array([home]), np.array([away]))
        p_dc = outcome_probs(lam, mu, self.dc.rho)[0]
        return {"Elo_pH": p_elo[0], "Elo_pD": p_elo[1], "Elo_pA": p_elo[2], "Dixon-Coles_pH": p_dc[0],
                "Dixon-Coles_pD": p_dc[1], "Dixon-Coles_pA": p_dc[2], "lam": float(lam[0]), "mu": float(mu[0])}

    def probabilities(self, home: int, away: int, market_odds: np.ndarray | None = None) -> dict:
        """Probabilidades del modelo y, si hay cuotas de referencia, combinadas con el mercado."""
        p_elo = self.logit.predict(np.array([self._elo_diff(home, away)]))
        lam, mu = self.dc.expected_goals(np.array([home]), np.array([away]))
        p_dc = outcome_probs(lam, mu, self.dc.rho)
        out = {"p_model": pool([p_elo, p_dc], np.array(self.params["w_models"]))[0],
               "lam": float(lam[0]), "mu": float(mu[0])}
        if market_odds is not None:
            p_mkt = proportional(np.asarray(market_odds, dtype=float)[None, :])
            out["p_market"] = p_mkt[0]
            out["p_final"] = pool([p_elo, p_dc, p_mkt], np.array(self.params["w_blend"]))[0]
        return out

    def _confidence(self, home, away, p_elo, p_dc) -> dict:
        """Heurística: datos recientes de ambos equipos y acuerdo entre Elo y Dixon-Coles."""
        n = min(self.recent_counts.get(home, 0), self.recent_counts.get(away, 0))
        disagreement = float(np.max(np.abs(p_elo - p_dc)))
        level = "alta" if n >= 20 and disagreement < 0.05 else "baja" if n < 8 or disagreement > 0.10 else "media"
        return {"level": level, "min_recent_matches": int(n), "elo_dc_max_diff": disagreement}

    def _betting(self, odds, p_elo, p_dc, p_model) -> dict:
        p_mkt = proportional(odds[None, :])
        p_final = pool([p_elo, p_dc, p_mkt], np.array(self.params["w_blend"]))[0]
        ev_final = p_final * odds - 1
        min_ev = self.params["min_ev"]
        best = int(np.argmax(ev_final))
        return {
            "odds": odds, "implied": 1 / odds, "margin": float(overround(odds[None, :])[0]),
            "p_market_fair": p_mkt[0], "p_final": p_final,
            "edge_pp": p_model - 1 / odds, "ev_model": p_model * odds - 1, "ev_final": ev_final,
            "min_ev": min_ev, "best": best,
            "recommend": bool(ev_final[best] > min_ev),
        }
