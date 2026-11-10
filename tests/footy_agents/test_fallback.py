"""Respaldo verificable, memoria tras errores y horarios calculados por herramientas."""

import asyncio
import sqlite3

import pytest

from footy_agents import memory, orchestrator, tools
from footy_agents.fallback import verified_summary
from footy_agents.grounding import verify_numbers
from footy_agents.llm import LLMUnavailable, TextDelta, ToolCall
from footy_agents.schemas import ChatRequest, ToolCallRecord, UserPreferences
from footy_agents.web import router


class FakeLLM:
    def __init__(self, *turns):
        self.turns = iter(turns)
        self.messages = []

    def stream_chat(self, messages, tools=None):
        self.messages.append([dict(m) for m in messages])
        turn = next(self.turns)
        if isinstance(turn, Exception):
            raise turn
        yield from turn


def record(name, data):
    return ToolCallRecord(tool_name=name, result=data, arguments={}, success=True, execution_time_ms=0)


def answer(events):
    return "".join(e.data["delta"] for e in events if e.event == "token")


def test_double_failure_returns_verified_canonical_data(monkeypatch):
    data = {"match_id": 181043, "home": "Colombia", "away": "Chile", "status": "no_pinnacle",
            "probabilities_1x2": {"summary": "Colombia 67.5% · empate 20.0% · Chile 12.5%", "favorite": "Colombia"}}
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda match_id: data)
    client = FakeLLM([ToolCall("a", "analyze_match", {"match_id": 181043})],
                     [TextDelta("Probabilidad 99.99%.")], [TextDelta("Probabilidad 99.99%.")])
    events = list(orchestrator.run_chat(client, "Analiza el partido", UserPreferences()))
    assert data["probabilities_1x2"]["summary"] in answer(events)
    assert "Favorito: Colombia." in answer(events) and "Sin precio de Pinnacle" in answer(events)
    assert "99.99" not in answer(events) and orchestrator.SAFE_TEXT not in answer(events)
    assert events[-1].data["success"]
    assert any(e.event == "step" and e.data.get("text") ==
               "Se entrega el resumen verificado de los datos consultados" for e in events)
    assert verify_numbers(answer(events), [record("analyze_match", data)]).verified


def test_double_failure_without_data_stays_safe():
    bad = [TextDelta("La cuota es 99.99.")]
    events = list(orchestrator.run_chat(FakeLLM(bad, bad, bad), "una consulta", UserPreferences()))
    assert answer(events) == orchestrator.SAFE_TEXT and not events[-1].data["success"]


@pytest.mark.parametrize("failure", ["empty", "leak", "limit"])
def test_useful_data_also_survives_terminal_model_failures(monkeypatch, failure):
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    data = {"summary": "Datos consultados.", "favorite": "Chile"}
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda match_id: data)
    call = [ToolCall("a", "analyze_match", {"match_id": 181043})]
    turns = {"empty": [call, []], "leak": [call, [TextDelta("analyze_match")], [TextDelta("analyze_match")]],
             "limit": [call, call, call, call]}
    events = list(orchestrator.run_chat(FakeLLM(*turns[failure]), "Analiza el partido", UserPreferences()))
    assert "Favorito: Chile." in answer(events) and events[-1].data["success"]


def test_calendar_fallback_uses_tool_local_time():
    row = {"home": "Colombia", "away": "Chile", "kickoff_local": "vie 13-11, 21:00 hora de Chile"}
    records = [record("get_upcoming_matches", [row])]
    text = verified_summary(records)
    assert "Colombia vs Chile: vie 13-11, 21:00 hora de Chile" in text
    assert "Pinnacle" in text and verify_numbers(text, records).verified


def test_summary_order_and_invalid_or_failed_data():
    records = [record("get_coverage", {"freshness": "Actualizado.", "rule": "Solo Pinnacle."}),
               record("get_system_performance", {"assessment": "Rendimiento disponible."}),
               record("get_stake_limits", {"limits_text": "Límites disponibles."}),
               record("get_team_form", {"form_text": "Forma disponible."}),
               record("simulate_match", {"summary": "Probabilidades disponibles.", "favorite": "Chile"})]
    text = verified_summary(records)
    assert text.index("Probabilidades") < text.index("Forma") < text.index("Límites") < text.index("Rendimiento")
    assert text.index("Rendimiento") < text.index("Actualizado") < text.index("Pinnacle")
    records[-1].success = False
    assert "Probabilidades" not in verified_summary(records)
    assert verified_summary([record("analyze_match", {"error": "No existe"})]) == ""
    assert verified_summary([record("analyze_match", {"status": "no_pinnacle"})]) == ""
    assert verified_summary([record("get_stake_limits", {"limits_text": "El tope diario es 2 %."})]) == ""


@pytest.mark.parametrize("kickoff,expected", [
    ("2026-11-14T00:00:00Z", "vie 13-11, 21:00 hora de Chile"),
    ("2026-07-14T00:00:00Z", "lun 13-07, 20:00 hora de Chile"),
])
def test_three_tools_provide_local_kickoff(monkeypatch, kickoff, expected):
    match = {"ref": "m:181043", "home": "Colombia", "away": "Chile", "kickoff": kickoff,
             "league": "FRI", "p_official": [.6, .25, .15]}
    monkeypatch.setattr(tools.service, "upcoming", lambda: [match])
    def database():
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE teams (name TEXT)")
        return conn
    monkeypatch.setattr(tools, "connect", database)
    class Clock(tools.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, tzinfo=tz)
    monkeypatch.setattr(tools, "datetime", Clock)
    rows = [tools.tool_get_upcoming_matches()[0], tools.tool_analyze_match(181043),
            next(row for row in tools.tool_find_team("Chile") if row["exact"])["next_match"]]
    for row in rows:
        assert row["kickoff_local"] == expected
        assert verify_numbers(expected, [record("datos", row)]).verified
        assert not verify_numbers(expected.replace("20:00", "21:59").replace(
            "21:00", "21:59"), [record("datos", row)]).verified
    assert tools.kickoff_local(None) is None
    with pytest.raises(ValueError, match="zona"):
        tools.kickoff_local("2026-11-14T00:00:00")


@pytest.mark.parametrize("fallback", [False, True])
def test_entities_survive_failed_turn_and_followup(tmp_path, monkeypatch, fallback):
    path = tmp_path / "memory.sqlite"
    monkeypatch.setattr(router, "connect", lambda: sqlite3.connect(path))
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setattr(orchestrator, "is_follow_up", lambda message, entities: message.startswith("¿Y"))
    entity = {"match_id": 181043, "home": "Colombia", "away": "Chile"}
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "find_team", lambda name: [
        {"team": "Chile", "exact": True, "next_match": entity}])
    def chat(message, client):
        response = router.chat(ChatRequest(message=message), client)
        async def collect():
            return "".join([chunk async for chunk in response.body_iterator])
        return asyncio.run(collect())
    if fallback:
        monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda match_id: {
            **entity, "summary": "Datos consultados.", "favorite": "Colombia"})
        bad = [TextDelta("La probabilidad es 99.99%.")]
        body = chat("Analiza la roja", FakeLLM([ToolCall("a", "analyze_match", {"match_id": 181043})], bad, bad))
        assert "Se entrega el resumen verificado" in body and '"success": true' in body
    else:
        body = chat("Analiza la roja", FakeLLM([ToolCall("a", "find_team", {"name": "la roja"})], LLMUnavailable()))
        assert '"success": false' in body
    with sqlite3.connect(path) as db:
        assert memory.recent_entities(db, "default") == entity
        past = memory.history(db, "default")
        assert bool(past) is fallback  # solo se recuerda texto verificado, también el de respaldo
        assert "99.99" not in str(past)
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda match_id: entity)
    client = FakeLLM([ToolCall("b", "analyze_match", {"match_id": 181043})], [TextDelta("Datos consultados.")])
    chat("¿Y quién es favorito?", client)
    assert "match_id=181043" in client.messages[0][0]["content"]
