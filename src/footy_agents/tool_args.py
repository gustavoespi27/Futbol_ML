"""Contratos únicos para validación de herramientas y generación del esquema anunciado."""

from math import isfinite
from typing import Literal

from pydantic import Field, field_validator

from footy.betting import pro
from footy_agents.calendar import requested_dates
from footy_agents.schemas import AgentSchema
from footy_agents.watch_schemas import CancelArgs, FavoriteArgs, WatchArgs


class UpcomingArgs(AgentSchema):
    limit: int = Field(default=10, ge=1, le=20, strict=True)
    league: str | None = Field(default=None, min_length=1, max_length=100)
    team: str | None = Field(default=None, min_length=1, max_length=100)
    day: str | None = Field(default=None, min_length=1, max_length=20)
    important: bool = Field(default=False, strict=True)
    exclude_ids: list[int] = Field(default_factory=list, max_length=20)
    category: Literal["international", "clubs"] | None = None

    @field_validator("day")
    @classmethod
    def valid_day(cls, value: str | None) -> str | None:
        if value is not None:
            requested_dates(value)
        return value


class ValueArgs(AgentSchema):
    min_edge: float = Field(default=pro.MIN_EDGE, ge=pro.MIN_EDGE, le=1, allow_inf_nan=False)

    @field_validator("min_edge", mode="before")
    @classmethod
    def minimum_policy(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("La ventaja mínima debe ser numérica")
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError("La ventaja mínima debe ser finita")
        return max(numeric, pro.MIN_EDGE)


class RecommendationArgs(AgentSchema):
    section: Literal["todas", "valor", "fiables", "casi_valor"] = "todas"
    limit: int = Field(default=3, ge=1, le=5)


class SimulationArgs(AgentSchema):
    league: str | None = Field(default=None, min_length=1, max_length=100)
    home_team: str = Field(min_length=1, max_length=100)
    away_team: str = Field(min_length=1, max_length=100)


class StandingsArgs(AgentSchema):
    league: str = Field(min_length=1, max_length=100)
    part: Literal["top", "bottom", "all"] = "top"


class StakeArgs(AgentSchema):
    bankroll: float = Field(ge=0, allow_inf_nan=False)


class PerformanceArgs(AgentSchema):
    pass


class FindTeamArgs(AgentSchema):
    name: str = Field(min_length=2, max_length=100)


class AnalyzeArgs(AgentSchema):
    match_id: int = Field(ge=1)


class CoverageArgs(AgentSchema):
    pass


class TeamFormArgs(AgentSchema):
    team: str = Field(min_length=2, max_length=100)


TOOL_MODELS = {
    "get_upcoming_matches": UpcomingArgs,
    "get_value_bets": ValueArgs,
    "get_recommendations": RecommendationArgs,
    "simulate_match": SimulationArgs,
    "get_league_standings": StandingsArgs,
    "get_system_performance": PerformanceArgs,
    "get_stake_limits": StakeArgs,
    "find_team": FindTeamArgs,
    "analyze_match": AnalyzeArgs,
    "request_odds": AnalyzeArgs,
    "get_coverage": CoverageArgs,
    "get_team_form": TeamFormArgs,
    "create_watch": WatchArgs,
    "list_watches": PerformanceArgs,
    "cancel_watch": CancelArgs,
    "add_favorite": FavoriteArgs,
}

DESCRIPTIONS = {
    "request_odds": ("Usa para «Compara cuotas de ese partido»: match_id conocido; delega al Ojeador y compara casas. "
                     "No calcula ventaja sin Pinnacle ni inventa cuotas ausentes."),
    "create_watch": ("Usa para «Avísame si aparece Pinnacle»: un match_id conocido o team y una condición. "
                     "No inventes ids; primero find_team/analyze_match. Una llamada por condición."),
    "list_watches": ("Usa para «¿Qué vigilas?» o «mis alertas»: lista vigilancias con ids. "
                     "No crea ni cancela objetivos."),
    "cancel_watch": "Usa para «Deja de vigilar el id 3»: requiere id real de list_watches. No es un match_id.",
    "add_favorite": "Usa para «Agrega a favoritos Colo Colo»: team o league. No crea vigilancias ni apuestas.",
    'get_upcoming_matches': ('Usa para calendario: «¿Qué partidos importantes hay el jueves?»: day, important, '
        'category y exclude_ids. No para análisis de un partido conocido: usa analyze_match.'),
    'get_value_bets': ('Usa para ventaja Pinnacle: «¿Hay apuestas con valor?». No para favoritos '
        'ni explicar cobertura: usa analyze_match o get_coverage.'),
    'get_recommendations': ('Usa para «recomendaciones de la máquina», «más fiables» o «casi con valor»: '
        'pestañas de Apuestas con ejemplos. No para analizar un partido: usa analyze_match.'),
    'simulate_match': ('Usa para cruce hipotético, también entre ligas: «Simula Colo Colo contra Barcelona»; '
        'league es opcional. No para un partido del calendario: usa analyze_match.'),
    'get_league_standings': ('Usa para posiciones: «¿Cómo va Colo Colo en la tabla?». No para pronóstico '
        'ni forma detallada.'),
    'get_system_performance': ('Usa para métricas: «¿Cuál es el rendimiento del sistema?». No para '
        'pronosticar un partido.'),
    'get_stake_limits': ('Usa para montos: «¿Cuánto arriesgar con banca de 100.000?». No para elegir '
        'apuestas ni prometer ganancias.'),
    'find_team': ('Usa para resolver nombre/apodo: «Analiza a la roja». No repitas si ya '
        'tienes match_id; un exacto con next_match permite analyze_match directo.'),
    'analyze_match': ('Usa para «¿Quién gana Colombia–Chile?»: requiere match_id de find_team o '
        'get_upcoming_matches. No para encuentro hipotético ni resolver apodos.'),
    'get_team_form': ('Usa para forma: «¿Cómo llega Colo Colo?». No sustituye analyze_match para '
        'favorito ni get_league_standings para tabla completa.'),
    'get_coverage': ('Usa para cobertura/frescura: «¿Por qué no hay apuestas?». No para '
        'pronóstico ni montos; consulta analyze_match o get_stake_limits.'),
}

OPENAI_TOOLS_SPEC = [
    {
        "type": "function",
        "function": {"name": name, "description": DESCRIPTIONS[name], "parameters": model.model_json_schema()},
    }
    for name, model in TOOL_MODELS.items()
]
