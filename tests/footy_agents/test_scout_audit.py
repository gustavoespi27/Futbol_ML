"""Correcciones de auditoría: preguntas de cuotas resueltas sin memoria previa."""

import pytest

from footy_agents import orchestrator, routing, tools
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.observations import observe
from footy_agents.schemas import ToolCallRecord, UserPreferences

ENTITY = {"match_id": 42, "home": "Argentina", "away": "Uruguay"}
COMPARISON = "Gana Argentina: mejor 2.25 en DraftKings.\nSin Pinnacle no hay valor medible; son precios ofrecidos."
DATA = {**ENTITY, "status": "no_pinnacle", "comparison_text": COMPARISON, "best_odds": 2.25}


class FakeLLM:
    def __init__(self, *turns):
        self.turns = iter(turns)
        self.messages = []

    def stream_chat(self, messages, tools=None):
        self.messages.append([dict(m) for m in messages])
        yield from next(self.turns)


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [])
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY, "get_upcoming_matches", lambda **_: [{**ENTITY, "has_pinnacle_price": False}]
    )
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY, "find_team", lambda **_: [{"team": "Argentina", "exact": True, "next_match": ENTITY}]
    )
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "request_odds", lambda **_: DATA)


@pytest.mark.parametrize(
    "question",
    ["¿cuánto paga Argentina contra Uruguay?", "¿Hay cuotas de Argentina?", "compara cuotas", "qué casa paga más"],
)
def test_quote_intent_exists_before_entity(question):
    assert routing.intent_route(question) == ("request_odds", {})
    assert routing.intent_route(question, ENTITY) == ("request_odds", {"match_id": 42})
    assert routing.intent_route("Avísame si aparecen cuotas", ENTITY)[0] == "create_watch"


@pytest.mark.parametrize("preload", [True, False])
def test_quote_recovery_after_calendar_or_find_team(monkeypatch, preload):
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: {"team": "Argentina"} if preload else None)
    turns = [] if preload else [[ToolCall("f", "find_team", {"name": "Argentina"})]]
    client = FakeLLM(
        *turns,
        [TextDelta("Argentina es favorito.")],
        [ToolCall("r", "request_odds", {"match_id": 42})],
        [TextDelta(COMPARISON)],
    )
    consulted = {}
    events = list(
        orchestrator.run_chat(
            client, "¿cuánto paga Argentina contra Uruguay?", UserPreferences(), consulted_entities=consulted
        )
    )
    assert events[-1].data["success"]
    assert "".join(e.data["delta"] for e in events if e.event == "token") == COMPARISON
    assert any(e.event == "step" and e.data["kind"] == "recovery" for e in events)
    recovery = next(
        m["content"]
        for sent in client.messages
        for m in sent
        if m["role"] == "user" and "consulta request_odds" in m["content"]
    )
    assert "42" in recovery
    assert consulted["match_id"] == 42


@pytest.mark.parametrize("count,args,expected", [(1, {}, True), (2, {"team": "Argentina"}, True), (2, {}, False)])
def test_specific_calendar_offers_delegation(count, args, expected):
    record = ToolCallRecord(
        tool_name="get_upcoming_matches",
        arguments=args,
        result=[{**ENTITY, "has_pinnacle_price": False} for _ in range(count)],
        success=True,
        execution_time_ms=0,
    )
    assert ("request_odds" in observe(record).options) is expected


def test_comparison_with_intro_is_verified_without_repair(monkeypatch):
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda **_: {**ENTITY, "status": "no_pinnacle"})
    answer = "Míster, aquí está la comparación de precios:\n\n" + COMPARISON
    client = FakeLLM([ToolCall("r", "request_odds", {"match_id": 42})], [TextDelta(answer)])
    events = list(orchestrator.run_chat(client, "Compara cuotas", UserPreferences(), entities=ENTITY))
    assert events[-1].data["success"]
    assert "".join(e.data["delta"] for e in events if e.event == "token") == answer
    assert not any(e.event == "step" and e.data["kind"] == "repair" for e in events)
    assert len(client.messages) == 2


@pytest.mark.parametrize(
    "bad",
    [
        COMPARISON + "\nHay apuestas con valor.",
        COMPARISON + "\nNo hay apuestas con valor.",
        COMPARISON + "\nEl tope es 2 % por apuesta.",
        COMPARISON + "\nLa cuota podría ser 9999.99.",
        COMPARISON.splitlines()[0],
    ],
)
def test_comparison_context_cannot_add_claims_or_omit_lines(monkeypatch, bad):
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda **_: {**ENTITY, "status": "no_pinnacle"})
    client = FakeLLM([ToolCall("r", "request_odds", {"match_id": 42})], [TextDelta(bad)], [TextDelta(COMPARISON)])
    events = list(orchestrator.run_chat(client, "Compara cuotas", UserPreferences(), entities=ENTITY))
    assert events[-1].data["success"]
    assert "".join(e.data["delta"] for e in events if e.event == "token") == COMPARISON
    assert any(e.event == "step" and e.data["kind"] == "repair" for e in events)



@pytest.mark.parametrize("message, tool", [
    ("¿hay cuotas con valor hoy?", "get_value_bets"),
    ("¿qué cuotas tienen ventaja?", "get_value_bets"),
    ("¿cuánto paga Argentina contra Uruguay?", "request_odds"),
    ("¿y las cuotas?", "request_odds"),
])
def test_value_questions_do_not_go_to_the_odds_comparator(message, tool):
    from footy_agents.routing import intent_route
    assert intent_route(message, None)[0] == tool
