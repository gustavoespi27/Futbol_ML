"""Contratos estrictos de objetivos, alertas y decisiones del vigía."""

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from footy_agents.schemas import AgentSchema

Condition = Literal[
    "kickoff_soon", "pinnacle_available", "value_appears", "line_move", "probability_shift", "coverage_lost"
]
CONDITION_LABELS = {
    "kickoff_soon": "inicio en las próximas 24 horas",
    "pinnacle_available": "precio de Pinnacle disponible",
    "value_appears": "aparición de ventaja elegible",
    "line_move": "movimiento de Pinnacle de al menos 5 %",
    "probability_shift": "cambio de probabilidad de al menos 3 puntos porcentuales",
    "coverage_lost": "pérdida de cobertura Pinnacle",
}


class WatchArgs(AgentSchema):
    match_id: int | None = Field(default=None, ge=1, strict=True)
    team: str | None = Field(default=None, min_length=2, max_length=100)
    condition: Condition = Field(description="kickoff_soon: inicio en 24 h; pinnacle_available: precio Pinnacle; "
                                 "value_appears: selección elegible con ventaja; line_move: Pinnacle cambia 5 %; "
                                 "probability_shift: cambio de 3 pp; coverage_lost: pierde Pinnacle")

    @model_validator(mode="after")
    def one_target(self) -> Self:
        if (self.match_id is None) == (self.team is None):
            raise ValueError("Indica exactamente un match_id o un equipo")
        return self


class CancelArgs(AgentSchema):
    id: int = Field(ge=1, strict=True)


class FavoriteArgs(AgentSchema):
    team: str | None = Field(default=None, min_length=2, max_length=100)
    league: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def one_target(self) -> Self:
        if (self.team is None) == (self.league is None):
            raise ValueError("Indica exactamente un equipo o una liga")
        return self


class Watch(AgentSchema):
    id: int
    user_id: str
    match_id: int | None
    team: str | None
    condition: Condition
    status: Literal["active", "fulfilled", "cancelled"]
    created_at: str
    fulfilled_at: str | None


class Alert(AgentSchema):
    id: int
    created_at: str
    match_id: int
    watch_id: int | None
    kind: str
    priority: int
    facts: dict[str, Any]
    text: str
    read: bool
    expires_at: str | None = None


class Decision(AgentSchema):
    match_id: int | None
    watch_id: int | None = None
    user_id: str
    kind: str
    selected: bool
    reason: str


class WatchRun(AgentSchema):
    id: int
    run_at: str
    perceived: int
    perception: dict[str, Any] = Field(default_factory=dict)
    decisions: list[Decision]
    actions: int
    elapsed_ms: float


class ReadAlert(AgentSchema):
    user_id: str = Field(default="default", min_length=1, max_length=100)
