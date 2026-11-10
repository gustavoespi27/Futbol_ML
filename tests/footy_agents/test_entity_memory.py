"""Ruteo y memoria de entidades sin persistir cifras del motor."""
import sqlite3
from datetime import datetime, timedelta, timezone

from footy_agents import memory, orchestrator, tools
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.schemas import ToolCallRecord, UserPreferences
from footy_agents.tool_args import DESCRIPTIONS, TOOL_MODELS


def test_migration_and_entity_isolation():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE agent_chat_memory (id INTEGER PRIMARY KEY, user_id TEXT, question TEXT, "
               "answer TEXT, created_at TEXT)")
    memory.init_tables(db)
    memory.init_tables(db)
    entity = {"match_id": 42, "home": "Chile", "away": "Colombia", "league": "WCQ"}
    memory.remember(db, "u", "analiza", "respuesta", entity)
    memory.remember(db, "u", "hola", "hola")
    assert memory.recent_entities(db, "u") == entity
    assert memory.recent_entities(db, "otro") == {}
    assert memory.recent_entities(db, "u", datetime.now(timezone.utc) + timedelta(hours=1)) == {}
    memory.forget(db, "u")
    assert memory.recent_entities(db, "u") == {}


def test_entity_extraction_keeps_only_identity():
    for name, result in [
        ("analyze_match", {"match_id": 42, "home": "Chile", "away": "Colombia", "edge": .9}),
        ("simulate_match", {"home": "Chile", "away": "Colombia", "league": "WCQ"}),
        ("get_team_form", {"team": "Chile", "league_name": "WCQ", "last5_counts": {"won": 3}}),
        ("find_team", [{"team": "Chile", "exact": True, "next_match": {"match_id": 42}}]),
    ]:
        record = ToolCallRecord(tool_name=name, arguments={}, result=result, success=True, execution_time_ms=0)
        assert memory.entities_from(record)
        assert "edge" not in memory.entities_from(record)
        assert "last5_counts" not in memory.entities_from(record)
    record.result = [{"exact": False, "team": "Chile"}]
    assert memory.entities_from(record) == {}


def test_exact_team_direct_analysis_and_followup(monkeypatch):
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "find_team", lambda name: [
        {"team": "Chile", "exact": True, "next_match": {
            "match_id": 42, "home": "Chile", "away": "Colombia", "league": "WCQ"}}])
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda match_id: {
        "match_id": match_id, "home": "Chile", "away": "Colombia", "favorite": "Colombia"})

    class FakeLLM:
        def __init__(self, turns):
            self.turns = iter(turns)
            self.messages = []

        def stream_chat(self, messages, tools=None):
            self.messages.append([dict(m) for m in messages])
            yield from next(self.turns)

    first = FakeLLM([[ToolCall("a", "find_team", {"name": "la roja"})],
                     [ToolCall("b", "analyze_match", {"match_id": 42})], [TextDelta("Colombia es favorito.")]])
    entity = {}
    events = list(orchestrator.run_chat(first, "Analiza a la roja", UserPreferences(), consulted_entities=entity))
    assert [e.data["tool"] for e in events if e.event == "tool_start"] == ["find_team", "analyze_match"]
    second = FakeLLM([[TextDelta("Colombia es favorito.")]])
    events = list(orchestrator.run_chat(second, "¿Y quién es favorito?", UserPreferences(), entities=entity))
    assert "match_id=42 (Chile vs Colombia)" in second.messages[0][0]["content"]
    assert [e.data["args"] for e in events if e.event == "tool_start"] == [{"match_id": 42}]
    assert events[-1].data["success"]

    assert second.messages[0][-1]["role"] == "tool"
    assert not any(e.event == "step" and e.data["kind"] == "recovery" for e in events)
    assert events[-1].data["success"]


def test_descriptions_are_brief_and_explicit():
    assert DESCRIPTIONS.keys() == TOOL_MODELS.keys()
    assert all(len(text) <= 200 and "No " in text and "«" in text for text in DESCRIPTIONS.values())
