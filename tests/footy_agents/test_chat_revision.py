"""Regresiones de procedencia, verificación previa y precarga determinista."""

import pytest

from footy_agents import orchestrator, tools
from footy_agents.grounding import verify_numbers
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.schemas import UserPreferences


class FakeLLM:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []

    def stream_chat(self, messages, tools=None):
        self.calls.append(([dict(m) for m in messages], tools))
        yield from self.turns.pop(0)


def run(client, message="hola"):
    return list(orchestrator.run_chat(client, message, UserPreferences()))


def text(events):
    return "".join(e.data["delta"] for e in events if e.event == "token")


def test_verifies_entire_answer_before_first_token():
    consumed = []

    class Stream:
        def stream_chat(self, *_):
            yield TextDelta("Hola. ")
            consumed.append(True)
            yield TextDelta("La cuota inventada es 9,99.")

    output = orchestrator.run_chat(Stream(), "hola", UserPreferences())
    first = next(output)
    assert consumed and first.event == "error"
    remaining = list(output)
    assert "9,99" not in text(remaining)
    assert remaining[-1].data["success"] is False


def test_discards_text_from_tool_iteration(monkeypatch):
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "get_upcoming_matches", lambda **_: [])
    events = run(FakeLLM([TextDelta("Cuota inventada 9,99"), ToolCall(id="x", name="get_upcoming_matches")],
                         [TextDelta("Sin partidos disponibles.")]))
    assert text(events) == "Sin partidos disponibles."
    assert events[-1].data["success"] is True


@pytest.mark.parametrize("retry,success", [("Respuesta disponible.", True), ("CallCheck get_value_bets", False)])
def test_pseudocall_retries_once(retry, success):
    client = FakeLLM([TextDelta("Llamando a la herramienta get_value_bets")], [TextDelta(retry)])
    events = run(client)
    assert len(client.calls) == 2
    assert events[-1].data["success"] is success
    assert not orchestrator.has_tool_leak(text(events))


@pytest.mark.parametrize("policy", ["¼ Kelly; 2% por apuesta y 10% diario; ventaja mínima 6%", "1/4 de Kelly"])
def test_policy_and_user_amounts_grounded(policy):
    assert verify_numbers(policy, []).verified
    assert verify_numbers("Banca $100.000", [], user_message="Tengo 100.000 pesos").verified
    assert not verify_numbers("Banca $200.000", [], user_message="Tengo 100.000 pesos").verified


def test_stake_limits_calculated_in_code():
    record = tools.execute_tool("get_stake_limits", {"bankroll": 100_000})
    assert record.success
    assert record.result["bankroll_clp"] == "$100.000"
    assert verify_numbers("Tope $2.000 por apuesta y $10.000 diario", [record]).verified
    assert not tools.execute_tool("get_stake_limits", {"bankroll": float("inf")}).success


def test_minimum_edge_clamped(monkeypatch):
    captured = []
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "get_value_bets", lambda **kw: captured.append(kw))
    assert tools.execute_tool("get_value_bets", {"min_edge": .01}).success
    assert captured == [{"min_edge": .06}]


def test_league_alias_and_unknown():
    assert tools.resolve_league("Chilean Primera Division") == "CHL"
    assert tools.resolve_league("Premier League") == "E0"
    with pytest.raises(ValueError, match="Códigos cercanos"):
        tools.resolve_league("Chil")


@pytest.mark.parametrize("question", ["¿Qué probabilidad tiene Botosani de ganar?", "Partidos de E0"])
def test_preload_before_inference(monkeypatch, question):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [
        {"home": "FC Botosani", "away": "Everton", "league": "E0", "p_official": [.5, .3, .2]}])
    monkeypatch.setattr(orchestrator, "upcoming_focus", tools.upcoming_focus)
    client = FakeLLM([TextDelta("Probabilidad local 50%.")])
    events = run(client, question)
    assert events[0].event == "tool_start"
    assert client.calls[0][0][-1]["role"] == "tool"
    assert events[-1].data["success"] is True
    row = tools.tool_get_upcoming_matches()[0]
    assert row["value_status"] == "sin_precio_pinnacle"
    assert not row["has_pinnacle_price"] and "valor" not in row["recommendation"]
