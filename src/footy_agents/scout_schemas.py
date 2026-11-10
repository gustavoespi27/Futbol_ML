"""Contratos públicos y estrictos de la percepción y bitácora del Ojeador."""

from typing import Literal

from pydantic import Field

from footy_agents.schemas import AgentSchema


class ScoutPerception(AgentSchema):
    match_id: int
    home: str
    away: str
    league: str
    kickoff: str
    hours_to_kickoff: float
    favorite: bool
    has_odds: bool
    has_pinnacle: bool
    last_capture: str | None = None
    event_id: str | None = None
    slug: str | None = None
    espn_date: str


class ScoutDecision(AgentSchema):
    match_id: int
    selected: bool
    reason: str
    source: Literal["espn", "api_football"]
    group: tuple[str, str] | None = None
    refresh_hours: float = 6


class ScoutRun(AgentSchema):
    id: int | None = None
    run_at: str
    perceived: int = Field(ge=0)
    perception: list[ScoutPerception] = []
    decisions: list[ScoutDecision] = []
    actions: int = Field(default=0, ge=0)
    inserted: int = Field(default=0, ge=0)
    elapsed_ms: float = 0
