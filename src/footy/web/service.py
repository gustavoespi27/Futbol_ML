"""Fachada pública de datos para el dashboard (la usan app.py, scripts/daily.py y ml_predict).

La lógica vive en footy.web.services, un submódulo por responsabilidad:
  catalog (ligas, países, continentes), context (probabilidades y opciones de un partido, próximos partidos),
  betting (semáforo, apuestas sugeridas, pronósticos fiables), combos (combinadas), evaluation (seguimiento,
  evaluación 2026, ligas) y simulator. Aquí solo se reexporta y se conectan los submódulos con los próximos partidos
  para conservar las firmas de siempre.
"""

from footy.web.services import betting as _betting
from footy.web.services import catalog as _catalog
from footy.web.services import context as _context
from footy.web.services import evaluation as _evaluation
from footy.web.services.catalog import CONTINENT, COUNTRY_ES, league_names
from footy.web.services.combos import combo, combo_history
from footy.web.services.common import data_through, public, to_json
from footy.web.services.context import (
    CONTEXT_TTL,
    DISPLAY_BOOKS,
    HORIZON_DAYS,
    LOCAL_TZ,
    PREDICTOR_DIR,
    PREDICTOR_TTL,
    REFERENCE_BOOKS,
    STALE_DAYS,
    context,
    match_context,
    predictor,
    sim_context,
    upcoming,
)
from footy.web.services.evaluation import backtest, leagues_list, ml_report, overview, tracking_data
from footy.web.services.simulator import predict, teams

__all__ = [
    "CONTEXT_TTL", "CONTINENT", "COUNTRY_ES", "DISPLAY_BOOKS", "HORIZON_DAYS", "LOCAL_TZ", "PREDICTOR_DIR",
    "PREDICTOR_TTL", "REFERENCE_BOOKS", "STALE_DAYS",
    "backtest", "clear_caches", "combo", "combo_history", "context", "current_suggestions", "data_through",
    "league_catalog", "league_names", "leagues_list", "match_context", "ml_report", "overview", "predict",
    "predictor", "public", "register_reliable", "register_suggestions", "reliable_data", "sim_context",
    "suggestions_data", "teams", "to_json", "tracking_data", "upcoming",
]


def clear_caches() -> None:
    _context.clear_caches()
    _evaluation.clear_caches()


def league_catalog() -> list[dict]:
    """Todas las competiciones con país y continente (en español) y sus partidos de los próximos días."""
    return _catalog.league_catalog(upcoming())


def current_suggestions(matches: list[dict] | None = None) -> dict:
    """Apuestas del apostador profesional (footy.betting.pro) para los próximos partidos."""
    return _betting.current_suggestions(matches if matches is not None else upcoming())


def suggestions_data() -> dict:
    return _betting.suggestions_data(upcoming())


def reliable_data() -> dict:
    """Pronósticos fiables de hoy, su historial de aciertos y el ajuste automático de probabilidades."""
    return _betting.reliable_data(upcoming())


def register_reliable(conn=None) -> dict:
    return _betting.register_reliable(upcoming(), conn)


def register_suggestions(conn=None) -> dict:
    """El apostador profesional coloca (en papel) sus apuestas antes del partido. Lo llama scripts/daily.py."""
    return _betting.register_suggestions(upcoming(), conn)
