"""Contratos únicos para validación de herramientas y generación del esquema anunciado."""

from pydantic import Field

from footy.betting import pro
from footy_agents.schemas import AgentSchema


class UpcomingArgs(AgentSchema):
    limit: int = Field(default=10, ge=1, le=20, strict=True)
    league: str | None = Field(default=None, min_length=1, max_length=20)
    team: str | None = Field(default=None, min_length=1, max_length=100)


class ValueArgs(AgentSchema):
    min_edge: float = Field(default=pro.MIN_EDGE, ge=pro.MIN_EDGE, le=1, allow_inf_nan=False)


class SimulationArgs(AgentSchema):
    league: str = Field(min_length=1, max_length=20)
    home_team: str = Field(min_length=1, max_length=100)
    away_team: str = Field(min_length=1, max_length=100)


class StandingsArgs(AgentSchema):
    league: str = Field(min_length=1, max_length=20)


class PerformanceArgs(AgentSchema):
    pass


TOOL_MODELS = {
    "get_upcoming_matches": UpcomingArgs,
    "get_value_bets": ValueArgs,
    "simulate_match": SimulationArgs,
    "get_league_standings": StandingsArgs,
    "get_system_performance": PerformanceArgs,
}

DESCRIPTIONS = {
    "get_upcoming_matches": "Próximos partidos: horario, equipos y probabilidades 1X2 oficiales. Filtra por equipo.",
    "get_value_bets": "Apuestas con ventaja frente al precio justo sin margen de Pinnacle.",
    "simulate_match": "Simula dos equipos de una liga: goles esperados, probabilidades 1X2 y marcadores.",
    "get_league_standings": "Tabla de posiciones y racha reciente de una liga.",
    "get_system_performance": "Rendimiento real del sistema, CLV, yield y versión del motor.",
}

OPENAI_TOOLS_SPEC = [
    {"type": "function", "function": {"name": name, "description": DESCRIPTIONS[name],
                                      "parameters": model.model_json_schema()}}
    for name, model in TOOL_MODELS.items()
]
