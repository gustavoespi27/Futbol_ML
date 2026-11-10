"""Delegación real entre capas con fetch simulado y FakeLLM, sin tráfico en pruebas."""

import pytest
import test_odds_scout_cycle as cycle
from test_odds_scout_parser import fixture

from footy.ingest.espn import Espn
from footy_agents import odds_comparison, odds_scout, orchestrator, routing, tools
from footy_agents.fallback import verified_summary
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.observations import observe
from footy_agents.schemas import ToolCallRecord, UserPreferences


@pytest.fixture
def db(tmp_path):
    yield from cycle.db.__wrapped__(tmp_path)


@pytest.fixture
def delegated(db, monkeypatch):
    class Clock(cycle.datetime):
        @classmethod
        def now(cls, tz=None):
            return cycle.NOW

    for module in (tools, odds_scout, odds_comparison):
        monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(tools, "connect", lambda: db)

    # closing() no debe cerrar la conexión del fixture, que se inspecciona después.
    class Keep:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            return self.conn

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(tools, "closing", Keep)
    calls = []

    def fetch(self, slug, dates):
        calls.append((slug, dates))
        return [fixture("close")]

    monkeypatch.setattr(Espn, "scoreboard", fetch)
    return calls


def test_request_delegates_only_target_then_uses_cache(db, delegated):
    first = tools.tool_request_odds(1)
    second = tools.tool_request_odds(1)
    assert first["delegated"] and not second["delegated"]
    assert len(delegated) == 1 and first["status"] == "no_pinnacle"
    assert db.execute("SELECT DISTINCT match_id FROM odds").fetchall()[0][0] == 1
    assert all(o["edge"] is None for o in first["selections"])
    with pytest.raises(ValueError):
        tools.tool_request_odds(999)


def test_comparison_observation_route_and_fallback():
    data = {
        "status": "no_pinnacle",
        "note": "Sin Pinnacle no hay valor medible; son precios ofrecidos.",
        "comparison_text": "Gana local: mejor 2.25 en DraftKings. Sin Pinnacle no hay valor medible.",
    }
    record = ToolCallRecord(
        tool_name="request_odds", arguments={"match_id": 1}, result=data, success=True, execution_time_ms=0
    )
    assert observe(record).status == "no_pinnacle"
    assert verified_summary([record], "Compara cuotas") == data["comparison_text"]
    for message in ("compara cuotas", "cuánto paga", "qué casa paga más"):
        assert routing.intent_route(message, {"match_id": 1}) == ("request_odds", {"match_id": 1})
    record.tool_name = "analyze_match"
    assert "request_odds" in observe(record).options


def test_fake_llm_delegates_and_preserves_verified_comparison(db, delegated, monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [])
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY,
        "analyze_match",
        lambda **kw: {"match_id": 1, "status": "no_pinnacle", "odds_status": "sin cuotas de ninguna casa todavía"},
    )

    class FakeLLM:
        count = 0

        def stream_chat(self, messages, tools=None):
            self.count += 1
            if self.count == 1:
                yield ToolCall("r", "request_odds", {"match_id": 1})
            else:
                yield TextDelta("Cuota inventada 9999.99")

    events = list(
        orchestrator.run_chat(
            FakeLLM(),
            "compara cuotas",
            UserPreferences(),
            entities={"match_id": 1, "home": "Armenia", "away": "Cyprus"},
        )
    )
    text = "".join(e.data["delta"] for e in events if e.event == "token")
    assert "DraftKings" in text and "Sin Pinnacle" in text and "9999" not in text
    assert events[-1].data["success"] and delegated
    assert any(e.event == "tool_start" and e.data["tool"] == "request_odds" for e in events)


def test_comparison_canonical_text_prevents_false_absence_of_value(monkeypatch):
    data = {
        "match_id": 1,
        "home": "Armenia",
        "away": "Cyprus",
        "status": "no_pinnacle",
        "comparison_text": "Gana Armenia: mejor 2.3 en DraftKings. Sin Pinnacle no hay valor medible.",
        "note": "Sin Pinnacle no hay valor medible.",
    }
    monkeypatch.setattr(tools.service, "upcoming", lambda: [])
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda **_: {"match_id": 1})
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "request_odds", lambda **_: data)

    class FakeLLM:
        def __init__(self):
            self.turns = iter(
                [
                    [ToolCall("r", "request_odds", {"match_id": 1})],
                    [TextDelta("No hay apuestas con valor en este partido.")],
                    [TextDelta(data["comparison_text"])],
                ]
            )

        def stream_chat(self, messages, tools=None):
            yield from next(self.turns)

    events = list(
        orchestrator.run_chat(
            FakeLLM(),
            "Analiza ese partido",
            UserPreferences(),
            entities={"match_id": 1, "home": "Armenia", "away": "Cyprus"},
        )
    )
    assert "".join(e.data["delta"] for e in events if e.event == "token") == data["comparison_text"]
    assert any(e.event == "step" and e.data["kind"] == "repair" for e in events)
