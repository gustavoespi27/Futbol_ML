"""Regresión de memoria entre temas e intención de recuperación, sin red ni motor real."""

import sqlite3

import pytest

from footy_agents import memory, orchestrator, routing, tools
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.schemas import ToolCallRecord, UserPreferences

ENTITY = {"match_id": 181043, "home": "Colombia", "away": "Chile", "league": "FRI"}


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setattr(routing, "upcoming_focus", lambda _: None)
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setattr(tools.service, "league_catalog", lambda: [
        {"code": "FRI", "name": "Amistosos"}, {"code": "CHL", "name": "Liga chilena"}])
    monkeypatch.setattr(tools.service, "upcoming", lambda: [ENTITY, {"home": "Arsenal", "away": "Chelsea"}])


@pytest.mark.parametrize("message,expected", [
    ("¿Y quién es favorito?", True), ("y mañana", True), ("¿Cómo ves ese partido?", True),
    ("¿Y Chile?", True), ("¿El mismo?", True), ("¿Y ahí?", True),
    ("¿Y la roja?", True), ("¿Y la U?", False), ("¿Y Arsenal?", False),
    ("¿Y la liga chilena?", False), ("¿Y CHL?", False),
    ("¿Qué tan fiable es el sistema?", False), ("¿Cuánto apostar con 100.000?", False),
    ("¿Qué apuestas con valor hay hoy?", False), ("¿Cómo llega Colo Colo?", False),
    ("y " + "a" * 78, False),
])
def test_is_follow_up(message, expected):
    assert routing.is_follow_up(message, ENTITY) is expected


@pytest.mark.parametrize("message,name,args", [
    ("¿Qué tan fiable es el sistema?", "get_system_performance", {}),
    ("¿Cuánto debería apostar si tengo 100.000 pesos?", "get_stake_limits", {"bankroll": 100000}),
    ("¿Por qué no hay apuestas?", "get_coverage", {}),
    ("¿Qué ventaja hay?", "get_value_bets", {}),
    ("¿Cómo llega?", "get_team_form", {}),
    ("¿Y la tabla?", "get_league_standings", {"league": "FRI"}),
    ("¿Y quién es favorito?", "analyze_match", {"match_id": 181043}),
])
def test_recovery_intent(message, name, args):
    assert routing.intent_route(message, ENTITY) == (name, args)


def test_upcoming_entities_single_and_team_filter():
    matches = [{**ENTITY, "kickoff": "2026-11-14T20:00:00Z"},
               {**ENTITY, "match_id": 99, "kickoff": "2026-11-15T20:00:00Z"}]
    def record(rows, args):
        return ToolCallRecord(tool_name="get_upcoming_matches", arguments=args, result=rows,
                              success=True, execution_time_ms=0)
    assert memory.entities_from(record(matches, {})) == {"shown_ids": [181043, 99]}
    assert memory.entities_from(record(matches[:1], {})) == {**ENTITY, "shown_ids": [181043]}
    assert memory.entities_from(record(list(reversed(matches)), {"team": "Chile"})) == {
        **ENTITY, "shown_ids": [99, 181043]}
    assert memory.entities_from(record([], {"team": "Chile"})) == {"shown_ids": []}


def test_ten_turn_conversation_has_no_contamination(monkeypatch):
    from scripts.eval_agent_routing import CONVERSATION

    class FakeLLM:
        def __init__(self, name, args, text, preloaded=False):
            self.turns = iter([[TextDelta(text)]] if preloaded else
                              [[ToolCall("t", name, args)], [TextDelta(text)]])
            self.messages = []

        def stream_chat(self, messages, tools=None):
            self.messages.append([dict(m) for m in messages])
            yield from next(self.turns)

    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda m: {"team": "Chile"} if "roja" in m else None)
    for name in tools.TOOLS_REGISTRY:
        monkeypatch.setitem(tools.TOOLS_REGISTRY, name, lambda **kwargs: {"note": "Datos del turno"})
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "get_upcoming_matches", lambda **kwargs: [ENTITY])
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda **kwargs: ENTITY)
    arguments = {"get_team_form": {"team": "Colo Colo"}, "simulate_match": {
        "league": "CHL", "home_team": "Colo Colo", "away_team": "Universidad de Chile"},
        "get_stake_limits": {"bankroll": 100000}, "analyze_match": {"match_id": 181043}}
    with sqlite3.connect(":memory:") as db:
        for i, (question, expected) in enumerate(CONVERSATION):
            text = ("Análisis consultado.", "El favorito es Colombia.", "Forma reciente del equipo.",
                    "Simulación hipotética lista.",
                    "Calendario disponible.", "Evaluación de ventaja.", "Cobertura de referencia.",
                    "Rendimiento histórico.",
                    "Topes de exposición.", "Política educativa.")[i]
            client = FakeLLM(expected, arguments.get(expected, {}), text, preloaded=i in (1, 3))
            consulted: dict = {}
            events = list(orchestrator.run_chat(client, question, UserPreferences(), history=memory.history(db, "u"),
                                               entities=memory.recent_entities(db, "u"),
                                               consulted_entities=consulted))
            if expected != "policy":
                assert expected in [e.data["tool"] for e in events if e.event == "tool_start"]
                sent = client.messages[0]
                if i == 1:
                    assert len(sent) == 6  # último turno, pregunta y par assistant/tool de la precarga
                    assert sent[-1]["role"] == "tool"
                    assert "match_id=181043" in sent[0]["content"]
                    assert any(e.event == "step" and "Continúa" in e.data.get("text", "") for e in events)
                elif i == 3:          # cruce hipotético: la simulación se precarga, sin contexto de turnos previos
                    assert len(sent) == 4 and "Contexto reciente" not in sent[0]["content"]
                    assert sent[-1]["role"] == "tool" and sent[-1]["tool_call_id"] == "preload_simulate_match"
                elif i != 0:
                    assert len(sent) == 2 and "Contexto reciente" not in sent[0]["content"]
            answer = "".join(e.data["delta"] for e in events if e.event == "token")
            memory.remember(db, "u", question, answer, consulted)


def test_recovery_uses_original_intent_after_wrong_tool(monkeypatch):
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "get_value_bets", lambda **kwargs: [{"note": "Sin selección"}])
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "get_system_performance", lambda: {"note": "Rendimiento consultado"})

    class FakeLLM:
        calls = []

        def stream_chat(self, messages, tools=None):
            self.calls.append([dict(m) for m in messages])
            yield from [[ToolCall("a", "get_value_bets")], [TextDelta("No hay valor.")],
                        [ToolCall("b", "get_system_performance")],
                        [TextDelta("Rendimiento consultado.")]][len(self.calls) - 1]

    client = FakeLLM()
    events = list(orchestrator.run_chat(client, "¿Qué tan fiable es el sistema?", UserPreferences(),
                                       history=[{"role": "assistant", "content": "Respuesta anterior de apuestas"}],
                                       entities=ENTITY))
    assert "get_system_performance" in client.calls[2][-1]["content"]
    assert "get_value_bets" not in client.calls[2][-1]["content"]
    assert events[-1].data["success"]
