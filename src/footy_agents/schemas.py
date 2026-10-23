"""Esquemas Pydantic v2 para la capa agéntica y preferencias de usuario.

Todos los esquemas usan extra="forbid" para mantener la consistencia estricta del contrato.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from footy.db.repository import utc_now

RiskProfile = Literal["conservative", "moderate", "aggressive"]


class AgentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class UserPreferences(AgentSchema):
    user_id: str = Field(default="default", description="Identificador único del usuario (por defecto 'default')")
    favorite_teams: list[str] = Field(
        default_factory=list,
        description="Lista de nombres canónicos de equipos favoritos"
    )
    favorite_leagues: list[str] = Field(
        default_factory=list,
        description="Lista de códigos de ligas preferidas (ej: 'CHL', 'ARG', 'PL')"
    )
    risk_profile: RiskProfile = Field(
        default="moderate",
        description="Perfil de riesgo: solo cambia el orden del feed; el stake sigue siendo 1/4 Kelly con topes 2%/10%"
    )
    bankroll: float = Field(
        default=1000.0,
        ge=1.0,
        description="Monto total del bankroll del usuario en su divisa local"
    )
    updated_at: str = Field(
        default_factory=utc_now,
        description="Fecha y hora de última modificación en ISO-8601 UTC"
    )


class FeedItem(AgentSchema):
    match_id: int
    home_team: str
    away_team: str
    league: str
    league_name: str = ""
    kickoff: str
    is_favorite_team: bool
    is_favorite_league: bool
    value_bets_count: int
    best_edge: float | None = None
    relevance_score: float = Field(
        description="Puntaje de relevancia determinista para ordenar el feed (mayor = más relevante)"
    )


class PersonalizedFeedResponse(AgentSchema):
    items: list[FeedItem]
    generated_at: str
    risk_profile: RiskProfile
    total_matches: int
    favorite_matches_count: int


class ToolCallRecord(AgentSchema):
    tool_name: str
    arguments: dict[str, Any]
    result: Any
    success: bool
    execution_time_ms: float
    error_message: str | None = None



class ChatRequest(AgentSchema):
    message: str = Field(min_length=1, max_length=2000)
    user_id: str = "default"


class ChatEvent(AgentSchema):
    """Un evento del stream SSE de /api/agent/chat (contrato con el frontend, CLAUDE.md sección 6)."""
    event: Literal["tool_start", "tool_result", "token", "done", "error"]
    data: dict[str, Any]

    def to_sse(self) -> str:
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False, default=str)}\n\n"
