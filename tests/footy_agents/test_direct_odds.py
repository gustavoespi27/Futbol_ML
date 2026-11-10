"""C7: el LLM elige la consulta; el comparador entrega la respuesta verificada sin otra inferencia."""

import pytest

from footy_agents import orchestrator, tools
from footy_agents.llm import LLMUnavailable, ToolCall
from footy_agents.schemas import UserPreferences

ENTITY = {"match_id": 42, "home": "Argentina", "away": "Uruguay"}


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [])
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda **_: {**ENTITY, "status": "no_pinnacle"})


class NoFurtherInference:
    def __init__(self, *calls):
        self.calls = calls
        self.inferences = 0

    def stream_chat(self, messages, tools=None):
        self.inferences += 1
        assert self.inferences == 1, "No debe inferir después de una comparación verificada"
        yield from self.calls


@pytest.mark.parametrize(
    "status,text",
    [
        ("no_odds", "Ninguna casa publica cuotas todavía para este partido; ESPN tampoco tiene precios disponibles."),
        (
            "no_pinnacle",
            "Gana Argentina: mejor 2.25 en DraftKings.\nSin Pinnacle no hay valor medible; son precios ofrecidos.",
        ),
        ("ok", "Gana Argentina: mejor 2.25 en DraftKings · Pinnacle justo 2.00 · ventaja +12.5 %"),
    ],
)
def test_successful_comparison_ends_turn_immediately(monkeypatch, status, text):
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY, "request_odds", lambda **_: {**ENTITY, "status": status, "comparison_text": text}
    )
    client = NoFurtherInference(ToolCall("r", "request_odds", {"match_id": 42}))
    consulted = {}
    events = list(
        orchestrator.run_chat(
            client, "Compara cuotas", UserPreferences(), entities=ENTITY, consulted_entities=consulted
        )
    )
    assert "".join(e.data["delta"] for e in events if e.event == "token") == text
    assert events[-1].data == {"iterations": 1, "success": True}
    assert consulted == ENTITY
    assert [e.data["tool"] for e in events if e.event == "tool_start"] == ["analyze_match", "request_odds"]
    assert any(e.event == "step" and "Sin precio de Pinnacle" in e.data["text"] for e in events)
    assert not any(e.event == "step" and e.data["kind"] == "repair" for e in events)


def test_batch_stops_after_first_successful_comparison(monkeypatch):
    seen = []

    def compare(match_id):
        seen.append(match_id)
        return {**ENTITY, "comparison_text": "Sin Pinnacle no hay valor medible; son precios ofrecidos."}

    monkeypatch.setitem(tools.TOOLS_REGISTRY, "request_odds", compare)
    client = NoFurtherInference(
        ToolCall("ok", "request_odds", {"match_id": 42}), ToolCall("invented", "request_odds", {"match_id": 123456})
    )
    events = list(orchestrator.run_chat(client, "Compara cuotas", UserPreferences(), entities=ENTITY))
    assert seen == [42] and events[-1].data["success"]


@pytest.mark.parametrize("message", ["¿Hay cuotas con valor hoy?", "¿Qué tan fiable es el sistema?"])
def test_other_intents_do_not_shortcut(monkeypatch, message):
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY, "request_odds", lambda **_: {**ENTITY, "comparison_text": "Cuotas consultadas."}
    )

    class Client:
        inferences = 0

        def stream_chat(self, messages, tools=None):
            self.inferences += 1
            if self.inferences == 1:
                yield ToolCall("r", "request_odds", {"match_id": 42})
            else:
                raise LLMUnavailable("segunda inferencia requerida")

    client = Client()
    events = list(orchestrator.run_chat(client, message, UserPreferences()))
    assert client.inferences == 2 and not events[-1].data["success"]


@pytest.mark.parametrize("valid", ["failed", "unverified"])
def test_failed_or_unverified_result_does_not_shortcut(monkeypatch, valid):
    def compare(**_):
        if valid == "failed":
            raise ValueError("sin datos")
        return {**ENTITY, "comparison_text": "Tope diario: 2 %."}

    monkeypatch.setitem(tools.TOOLS_REGISTRY, "request_odds", compare)

    class Client:
        inferences = 0

        def stream_chat(self, messages, tools=None):
            self.inferences += 1
            if self.inferences == 1:
                yield ToolCall("r", "request_odds", {"match_id": 42})
            else:
                raise LLMUnavailable("se necesita continuar")

    client = Client()
    events = list(orchestrator.run_chat(client, "Compara cuotas", UserPreferences()))
    assert client.inferences == 2 and not events[-1].data["success"]
    assert not any(e.event == "token" and "2 %" in e.data["delta"] for e in events)
