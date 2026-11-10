"""El seguimiento dispone de análisis fresco antes de que el modelo decida redactar."""

import json

import pytest

from footy_agents import orchestrator, tools
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.schemas import UserPreferences

ENTITY = {"match_id": 181043, "home": "Colombia", "away": "Chile"}
DATA = {
    **ENTITY,
    "status": "no_pinnacle",
    "probabilities_1x2": {"summary": "Colombia 67.5% · empate 20.0% · Chile 12.5%", "favorite": "Colombia"},
}


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [])
    monkeypatch.setattr(tools.service, "league_catalog", lambda: [])
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda match_id: DATA)


class FakeLLM:
    def __init__(self, *turns):
        self.turns = iter(turns)
        self.messages = []

    def stream_chat(self, messages, tools=None):
        self.messages.append([dict(m) for m in messages])
        yield from next(self.turns)


def test_followup_preloads_before_first_inference(monkeypatch):
    consulted = []

    def analyze(match_id):
        consulted.append(match_id)
        return DATA

    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", analyze)

    class CheckedLLM(FakeLLM):
        def stream_chat(self, messages, tools=None):
            assert consulted == [181043]
            assert messages[-2]["tool_calls"][0]["function"]["name"] == "analyze_match"
            assert json.loads(messages[-1]["content"])["status"] == "no_pinnacle"
            yield from super().stream_chat(messages, tools)

    client = CheckedLLM([TextDelta("Colombia es favorito.")])
    entities: dict = {}
    events = list(
        orchestrator.run_chat(
            client, "¿Y quién es favorito?", UserPreferences(), entities=ENTITY, consulted_entities=entities
        )
    )
    assert [e.data["tool"] for e in events if e.event == "tool_start"] == ["analyze_match"]
    assert events[0].data == {
        "kind": "observation",
        "memory": "continued",
        "text": "Continúa con Colombia vs Chile: se consulta el análisis actualizado",
    }
    assert any(e.event == "tool_result" and e.data["success"] for e in events)
    assert any(e.event == "step" and "Sin precio de Pinnacle" in e.data.get("text", "") for e in events)
    assert entities == ENTITY and events[-1].data["success"]


@pytest.mark.parametrize(
    "question,entities",
    [
        ("Hola", ENTITY),
        ("¿Y la U?", ENTITY),
        ("¿Y quién es favorito?", {"team": "Chile"}),
        ("¿Y quién es favorito?", {}),
    ],
)
def test_no_analysis_preload_for_new_topic_or_missing_match(question, entities):
    client = FakeLLM([TextDelta("Sigo aquí.")])
    events = list(orchestrator.run_chat(client, question, UserPreferences(), entities=entities))
    assert not any(e.event == "tool_start" for e in events)
    assert client.messages[0][-1]["role"] == "user"


def test_new_performance_topic_keeps_its_own_route(monkeypatch):
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY, "get_system_performance", lambda: {"assessment": "Rendimiento consultado."}
    )
    client = FakeLLM([ToolCall("p", "get_system_performance")], [TextDelta("Rendimiento consultado.")])
    events = list(orchestrator.run_chat(client, "¿Qué tan fiable es el sistema?", UserPreferences(), entities=ENTITY))
    assert [e.data["tool"] for e in events if e.event == "tool_start"] == ["get_system_performance"]


def test_double_failure_falls_back_to_preloaded_summary_and_favorite():
    bad = [TextDelta("Colombia gana con 99.99%.")]
    events = list(orchestrator.run_chat(FakeLLM(bad, bad), "¿Y quién es favorito?", UserPreferences(), entities=ENTITY))
    text = "".join(e.data["delta"] for e in events if e.event == "token")
    assert DATA["probabilities_1x2"]["summary"] in text and "Favorito: Colombia." in text
    assert "99.99" not in text and orchestrator.SAFE_TEXT not in text
    assert events[-1].data["success"]
