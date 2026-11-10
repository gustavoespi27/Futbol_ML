"""Elo de selecciones y conversión Poisson; parámetros ajustados solo en 2000–2021."""

import hashlib
import heapq
import json
import pickle
import sqlite3
import threading
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize

from footy import config
from footy.ingest import international as source
from footy.markets.scoreline import outcome_probs
from footy.models.elo import goal_multiplier

VERSION = "selecciones_elo_poisson_v1"
TRAIN_END = datetime(2022, 1, 1, tzinfo=timezone.utc)
PATH = config.PROJECT_ROOT / "data/cache/international.pkl"
_cached: tuple[int, "InternationalModel"] | None = None
_lock = threading.Lock()


def tournament_k(tournament: str) -> int:
    name = tournament.casefold()
    if "friendly" in name or "amistos" in name:
        return 20
    if any(word in name for word in ("qualification", "qualifier", "eliminatoria", "nations league")):
        return 40
    if name in {"fifa world cup", "wc", "copa del mundo"}:
        return 60
    if name in {"uefa euro", "euro", "eurocopa", "copa américa", "copa america", "african cup of nations",
                "africa cup of nations", "afc asian cup", "gold cup", "concacaf gold cup", "ofc nations cup"}:
        return 50
    return 30


def elo_history(matches: list[source.InternationalMatch]
                ) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray]:
    """Actualizaciones disponibles estrictamente antes del kickoff; nunca usa el resultado del mismo partido."""
    ratings: dict[str, float] = {}
    histories: dict[str, list[tuple[float, float]]] = {}
    pending: list[tuple[float, int, str, str, float]] = []
    differences = np.empty(len(matches))
    if any(a.kickoff > b.kickoff for a, b in zip(matches, matches[1:])):
        raise ValueError("Los resultados deben estar ordenados temporalmente")

    def apply(before: float) -> None:
        while pending and pending[0][0] < before:
            available, _, home, away, delta = heapq.heappop(pending)
            for team, change in ((home, delta), (away, -delta)):
                ratings[team] = ratings.get(team, 1500.0) + change
                histories.setdefault(team, []).append((available, ratings[team]))

    for index, match in enumerate(matches):
        apply(match.kickoff.timestamp())
        advantage = 100 if match.neutral is False else 0
        diff = ratings.get(match.home, 1500.0) - ratings.get(match.away, 1500.0) + advantage
        differences[index] = diff
        expected = 1 / (1 + 10 ** (-diff / 400))
        result = 1.0 if match.home_goals > match.away_goals else .5 if match.home_goals == match.away_goals else 0.0
        delta = (tournament_k(match.tournament) * goal_multiplier(match.home_goals - match.away_goals)
                 * (result - expected))
        heapq.heappush(pending, (match.available_at.timestamp(), index, match.home, match.away, delta))
    apply(float("inf"))
    packed = {team: (np.array([t for t, _ in rows]), np.array([r for _, r in rows]))
              for team, rows in histories.items()}
    return packed, differences


def goals(differences: np.ndarray, intercept: float, slope: float) -> tuple[np.ndarray, np.ndarray]:
    x = np.clip(np.asarray(differences, dtype=float) / 400, -4, 4)
    return np.exp(np.clip(intercept + slope * x, -3, 2.1)), np.exp(np.clip(intercept - slope * x, -3, 2.1))


@dataclass
class InternationalModel:
    histories: dict[str, tuple[np.ndarray, np.ndarray]]
    intercept: float
    slope: float
    baseline: np.ndarray
    signature: str
    names: source.TeamNames
    n_train: int

    def rating_at(self, team: str, kickoff: datetime) -> float:
        history = self.histories.get(team)
        if history is None:
            return 1500.0
        times, ratings = history
        index = bisect_left(times, kickoff.timestamp()) - 1
        return float(ratings[index]) if index >= 0 else 1500.0

    def predict(self, home: str, away: str, kickoff: datetime,
                neutral: bool | None = None) -> tuple[np.ndarray, float, float]:
        h, a = self.names.canonical(home), self.names.canonical(away)
        if h is None or a is None:
            raise ValueError("El modelo solo admite selecciones absolutas masculinas")
        diff = self.rating_at(h, kickoff) - self.rating_at(a, kickoff) + (100 if neutral is False else 0)
        lam, mu = goals(np.array([diff]), self.intercept, self.slope)
        return outcome_probs(lam, mu)[0], float(lam[0]), float(mu[0])


def fit(matches: list[source.InternationalMatch], names: source.TeamNames, signature: str = "") -> InternationalModel:
    matches = sorted(matches, key=lambda match: (match.kickoff, match.home, match.away))
    histories, diff = elo_history(matches)
    train = np.array([2000 <= match.kickoff.year <= 2021 and match.available_at < TRAIN_END for match in matches])
    if not train.any():
        raise ValueError("No hay resultados de ajuste entre 2000 y 2021")
    hg = np.array([match.home_goals for match in matches])[train]
    ag = np.array([match.away_goals for match in matches])[train]
    x = diff[train]

    def objective(parameters: np.ndarray) -> float:
        lam, mu = goals(x, *parameters)
        return float(np.mean(lam - hg * np.log(lam) + mu - ag * np.log(mu)))

    result = minimize(objective, np.array([.25, .65]), method="L-BFGS-B", bounds=[(-1, 1.2), (.05, 2)])
    if not result.success:
        raise ValueError("No convergió el ajuste Poisson internacional")
    y = np.where(hg > ag, 0, np.where(hg == ag, 1, 2))
    baseline = np.bincount(y, minlength=3).astype(float) + .5
    baseline /= baseline.sum()
    return InternationalModel(histories, float(result.x[0]), float(result.x[1]), baseline,
                              signature, names, int(train.sum()))


def load() -> InternationalModel | None:
    global _cached
    with _lock:
        try:
            stamp = PATH.stat().st_mtime_ns
            if _cached and _cached[0] == stamp:
                return _cached[1]
            saved = pickle.loads(PATH.read_bytes())
            if saved["version"] != VERSION or not isinstance(saved["model"], InternationalModel):
                return None
            _cached = (stamp, saved["model"])
            return _cached[1]
        except (OSError, ValueError, EOFError, AttributeError, KeyError, TypeError, pickle.UnpicklingError):
            return None


def prepare(conn: sqlite3.Connection, refresh: bool = False) -> dict:
    path = source.refresh_results(force=refresh)
    names = source.TeamNames()
    audit = source.audit_names(conn, names)
    matches = source.supplement(conn, source.read_results(path, names), names)
    extra = [(m.match_id, m.kickoff.isoformat(), m.home, m.away, m.home_goals, m.away_goals, m.neutral)
             for m in matches if m.match_id is not None]
    signature = hashlib.sha256(path.read_bytes() + source.ALIASES.read_bytes() + source.CATALOG.read_bytes() +
                               VERSION.encode() + TRAIN_END.isoformat().encode() +
                               json.dumps(extra).encode()).hexdigest()
    existing = load()
    if existing is not None and existing.signature == signature:
        return {"status": "sin cambios", "matches": len(matches), "supplement": len(extra), **audit}
    model = fit(matches, names, signature)
    source.atomic_write(PATH, pickle.dumps({"version": VERSION, "model": model}))
    return {"status": "actualizado", "matches": len(matches), "supplement": len(extra),
            "n_train": model.n_train, **audit}
