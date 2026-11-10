"""Contratos únicos para validación de herramientas y generación del esquema anunciado."""

from math import isfinite

from pydantic import Field, field_validator

from footy.betting import pro
from footy_agents.schemas import AgentSchema


class UpcomingArgs(AgentSchema):
    limit: int = Field(default=10, ge=1, le=20, strict=True)
    league: str | None = Field(default=None, min_length=1, max_length=100)
    team: str | None = Field(default=None, min_length=1, max_length=100)


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


class SimulationArgs(AgentSchema):
    league: str = Field(min_length=1, max_length=100)
    home_team: str = Field(min_length=1, max_length=100)
    away_team: str = Field(min_length=1, max_length=100)


class StandingsArgs(AgentSchema):
    league: str = Field(min_length=1, max_length=100)


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
    "simulate_match": SimulationArgs,
    "get_league_standings": StandingsArgs,
    "get_system_performance": PerformanceArgs,
    "get_stake_limits": StakeArgs,
    "find_team": FindTeamArgs,
    "analyze_match": AnalyzeArgs,
    "get_coverage": CoverageArgs,
    "get_team_form": TeamFormArgs,
}

DESCRIPTIONS = {
    'get_upcoming_matches': ('Usa para calendario: «¿Qué partidos hay hoy?». No para analizar un partido '
        'conocido: usa analyze_match.'),
    'get_value_bets': ('Usa para ventaja Pinnacle: «¿Hay apuestas con valor?». No para favoritos '
        'ni explicar cobertura: usa analyze_match o get_coverage.'),
    'simulate_match': ('Usa para encuentro hipotético: «Simula Colo Colo contra la U». No para un '
        'partido del calendario con match_id: usa analyze_match.'),
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
