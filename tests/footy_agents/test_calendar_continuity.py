"""Regresión de la conversación de Gustavo: calendario local, listas, cuotas y repetición."""

import json
import sqlite3
from datetime import date, datetime, timezone
from difflib import SequenceMatcher

import pytest

from footy_agents import calendar, grounding, memory, orchestrator, routing, tools
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.schemas import ToolCallRecord, UserPreferences

MATCH = {
    "ref": "m:181043",
    "home": "Colombia",
    "away": "Chile",
    "league": "FRIENDLY",
    "league_name": "Amistosos internacionales",
    "kickoff": "2026-11-14T00:00:00Z",
    "p_official": [0.675, 0.2, 0.125],
}
ENTITY = {"match_id": 181043, "home": "Colombia", "away": "Chile"}


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 10, 12, tzinfo=timezone.utc).astimezone(tz)


@pytest.fixture(autouse=True)
def controlled(monkeypatch):
    monkeypatch.setattr(tools, "datetime", Clock)
    monkeypatch.setattr(calendar, "datetime", Clock)
    monkeypatch.setattr(tools.service, "upcoming", lambda: [MATCH])
    monkeypatch.setattr(tools.service, "league_catalog", lambda: [])
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "request_odds", lambda **_: {
        **ENTITY, "status": "no_odds", "comparison_text": "Colombia vs Chile: sin cuotas de ninguna casa todavía."})


def record(data, name="analyze_match", args=None):
    return ToolCallRecord(tool_name=name, result=data, arguments=args or {}, success=True, execution_time_ms=0)


class FakeLLM:
    def __init__(self, *turns):
        self.turns = iter(turns)
        self.messages = []

    def stream_chat(self, messages, tools=None):
        self.messages.append([dict(m) for m in messages])
        yield from next(self.turns)


def test_public_dates_are_local_in_all_nested_payloads(monkeypatch):
    def db():
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE teams (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO teams VALUES (1, 'Chile')")
        return conn

    monkeypatch.setattr(tools, "connect", db)
    monkeypatch.setattr(
        tools.service,
        "team_profile",
        lambda _: {"name": "Chile", "upcoming": [{"opponent": "Colombia", "kickoff": MATCH["kickoff"]}]},
    )
    rows = [
        tools.tool_get_upcoming_matches()[0],
        tools.tool_analyze_match(181043),
        tools.tool_find_team("Chile")[0]["next_match"],
        tools.tool_get_team_form("Chile")["next_matches"][0],
    ]
    for row in rows:
        assert "kickoff" not in row
        assert row["local_date"] == "2026-11-13" and row["weekday"] == "viernes"
        assert row["kickoff_local"] == "vie 13-11, 21:00 hora de Chile"
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "list_watches", lambda **_: {"watches": [{"kickoff": MATCH["kickoff"]}]})
    payload = tools.execute_tool("list_watches", {}).result
    assert '"kickoff"' not in json.dumps(payload)
    assert payload["watches"][0]["local_date"] == "2026-11-13"


@pytest.mark.parametrize(
    "claim,valid",
    [
        ("viernes 14", False),
        ("viernes 13", True),
        ("sábado 13", False),
        ("13 de noviembre", True),
        ("14 de noviembre", False),
    ],
)
def test_claim_checks_local_weekday_and_date(claim, valid):
    assert grounding.check_claims(claim, [record(tools.tool_analyze_match(181043))]).verified is valid


@pytest.mark.parametrize("hour,valid", [("3:00 AM", False), ("05:00", True), ("5:00 AM", True)])
def test_qatar_hour_not_converted_by_model(hour, valid):
    data = calendar.local_fields("2026-11-10T08:00:00Z")
    assert grounding.verify_numbers(f"Qatar juega a las {hour}", [record(data)]).verified is valid


@pytest.mark.parametrize(
    "day,expected",
    [
        ("hoy", "2026-11-10"),
        ("mañana", "2026-11-11"),
        ("jueves", "2026-11-12"),
        ("lunes", "2026-11-16"),
        ("2026-11-13", "2026-11-13"),
    ],
)
def test_day_resolution(day, expected):
    assert calendar.requested_dates(day)[0].isoformat() == expected
    if day == "jueves":
        assert calendar.requested_dates(day, date(2026, 11, 12)) == [date(2026, 11, 12)]


def test_weekend_and_invalid_day():
    assert calendar.requested_dates("el finde") == [date(2026, 11, 14), date(2026, 11, 15)]
    assert calendar.requested_dates("finde", date(2026, 11, 15)) == [date(2026, 11, 15)]
    assert not tools.execute_tool("get_upcoming_matches", {"day": "ayer"}).success


def test_filters_day_priority_youth_started_and_exclusions(monkeypatch):
    matches = [
        dict(MATCH, ref="m:1", kickoff="2026-11-12T20:00:00Z"),
        dict(MATCH, ref="m:2", home="Qatar U23", kickoff="2026-11-12T21:00:00Z"),
        dict(MATCH, ref="m:3", league="E0", league_name="Premier League", kickoff="2026-11-12T23:00:00Z"),
        dict(MATCH, ref="m:4", league="WCQ", league_name="Eliminatorias", kickoff="2026-11-12T22:00:00Z"),
        dict(MATCH, ref="m:5", kickoff="2026-11-10T00:00:00Z"),
        MATCH,
    ]
    monkeypatch.setattr(tools.service, "upcoming", lambda: matches)
    rows = tools.tool_get_upcoming_matches(day="jueves", important=True)
    assert [r["match_id"] for r in rows] == [3, 4, 1]
    assert all(r["local_date"] == "2026-11-12" for r in rows)
    assert [r["match_id"] for r in tools.tool_get_upcoming_matches(day="jueves", important=True, exclude_ids=[3])] == [
        4,
        1,
    ]
    assert 5 not in [r["match_id"] for r in tools.tool_get_upcoming_matches()]


def test_empty_date_observation_and_fallback():
    result = tools.execute_tool("get_upcoming_matches", {"day": "jueves"})
    obs = orchestrator.observe(result)
    assert obs.status == "empty" and "jueves 12-11" in obs.note


@pytest.mark.parametrize(
    "question",
    [
        "sí, busca eso",
        "si, busca eso",
        "dale",
        "ok, otro",
        "¿Y más?",
        "¿Qué otro partido hay?",
        "¿Esa tiene cuotas?",
        "¿Eso cuándo es?",
    ],
)
def test_followup_accepts_references_without_match_id(question):
    assert routing.is_follow_up(question, {"shown_ids": [181043]})
    assert not routing.is_follow_up("¿Y la U?", {"shown_ids": [181043]})


def test_more_excludes_shown_and_passes_last_turn(monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [MATCH, dict(MATCH, ref="m:99", home="Peru")])
    client = FakeLLM([ToolCall("m", "get_upcoming_matches", {})], [TextDelta("También está Peru.")])
    hist = [
        {"role": "user", "content": "Viejo"},
        {"role": "assistant", "content": "Viejo"},
        {"role": "user", "content": "Lista"},
        {"role": "assistant", "content": "Colombia vs Chile."},
    ]
    out = {}
    events = list(
        orchestrator.run_chat(
            client,
            "¿Qué otro partido hay?",
            UserPreferences(),
            history=hist,
            entities={"shown_ids": [181043]},
            consulted_entities=out,
        )
    )
    assert out["shown_ids"] == [99]
    assert client.messages[0][1:3] == hist[-2:]
    args = next(e.data["args"] for e in events if e.event == "tool_start")
    assert args["exclude_ids"] == [181043]


def test_calendar_filter_cannot_be_overridden_by_llm():
    client = FakeLLM(
        [ToolCall("m", "get_upcoming_matches", {"day": "mañana", "important": False})],
        [TextDelta("No hay partidos el jueves 12-11 con ese filtro.")],
    )
    events = list(orchestrator.run_chat(client, "que partidos importantes hay el jueves?", UserPreferences()))
    args = next(e.data["args"] for e in events if e.event == "tool_start")
    assert args["day"] == "jueves" and args["important"] is True
    assert events[-1].data["success"]


def test_repeated_answer_repaired_specific_question():
    answer = "Colombia es favorito, sin precio de Pinnacle no se puede evaluar la ventaja."
    client = FakeLLM([ToolCall("r", "request_odds", {"match_id": 181043})],
                     [TextDelta(answer)], [TextDelta("Colombia vs Chile: sin cuotas de ninguna casa todavía.")])
    events = list(
        orchestrator.run_chat(
            client,
            "¿Y ese partido?",
            UserPreferences(),
            history=[{"role": "assistant", "content": answer}],
            entities=ENTITY,
        )
    )
    assert any(e.event == "step" and e.data["kind"] == "repair" for e in events)
    assert "Responde solo lo nuevo que se preguntó" in client.messages[-1][-1]["content"]
    emitted = "".join(e.data["delta"] for e in events if e.event == "token")
    assert SequenceMatcher(None, emitted, answer).ratio() < 0.8


def test_duplicate_repair_failure_uses_odds_fallback():
    answer = "Colombia es favorito, sin precio de Pinnacle no se puede evaluar la ventaja."
    events = list(
        orchestrator.run_chat(
            FakeLLM([ToolCall("r", "request_odds", {"match_id": 181043})],
                    [TextDelta(answer)], [TextDelta(answer)]),
            "¿Y ese partido?",
            UserPreferences(),
            history=[{"role": "assistant", "content": answer}],
            entities=ENTITY,
        )
    )
    emitted = "".join(e.data["delta"] for e in events if e.event == "token")
    assert emitted == "Colombia vs Chile: sin cuotas de ninguna casa todavía."
    assert events[-1].data["success"]


@pytest.mark.parametrize(
    "books,status",
    [
        ({}, "sin cuotas de ninguna casa todavía"),
        ({"Bet365": [2.0, 3.0, 4.0]}, "cuotas de 1 casas, sin Pinnacle"),
        ({"Pinnacle": [2.0, 3.0, 4.0], "Bet365": [2.1, 2.9, 4.2]}, "con Pinnacle"),
    ],
)
def test_odds_status_and_best_prices(monkeypatch, books, status):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [dict(MATCH, odds_1x2=books)])
    data = tools.tool_analyze_match(181043)
    assert data["odds_status"] == status
    if books:
        assert data["best_odds"][0]["selection"] == "Colombia"
        assert data["best_odds"][0]["odds"] == max(o[0] for o in books.values())
    else:
        assert data["best_odds"] == []


def test_memory_decision_uses_flag_not_copy():
    events = list(
        orchestrator.run_chat(
            FakeLLM([TextDelta("Colombia es favorito.")]), "¿Y quién es favorito?", UserPreferences(), entities=ENTITY
        )
    )
    with sqlite3.connect(":memory:") as db:
        memory.log_run(db, "u", "seguimiento", "2026-11-10T12:00:00Z", events, 1)
        steps = json.loads(db.execute("SELECT steps FROM agent_runs").fetchone()[0])
        assert steps[0]["detail"] == "Último turno y entidades"
        memory.remember(db, "u", "partido", "Colombia", ENTITY)
        memory.remember(db, "u", "tema nuevo", "Rendimiento", {})
        assert memory.recent_entities(db, "u") == {}


@pytest.mark.parametrize(
    "kickoff,bad,good",
    [
        (
            "2026-11-14T00:00:00Z",
            "Juega el viernes 14 de noviembre a las 21:00.",
            "Juega el viernes 13 de noviembre a las 21:00.",
        ),
        ("2026-11-10T08:00:00Z", "Juega a las 3:00 AM.", "Juega a las 05:00 hora de Chile."),
    ],
)
def test_fake_llm_repairs_dates_and_hours(monkeypatch, kickoff, bad, good):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [dict(MATCH, kickoff=kickoff)])
    client = FakeLLM([TextDelta(bad)], [TextDelta(good)])
    events = list(orchestrator.run_chat(client, "¿Y cuándo juega?", UserPreferences(), entities=ENTITY))
    assert any(e.event == "step" and e.data["kind"] == "repair" for e in events)
    assert "".join(e.data["delta"] for e in events if e.event == "token") == good
    assert events[-1].data["success"]


def test_other_after_analysis_excludes_current_match():
    assert calendar.calendar_args("¿Qué otro partido hay?", ENTITY)["exclude_ids"] == [181043]


def test_category_and_explicit_date_routing():
    assert routing.intent_route("partidos importantes el jueves") == (
        "get_upcoming_matches",
        {"day": "jueves", "important": True},
    )
    assert routing.intent_route("que partidos hay el jueves?") == ("get_upcoming_matches", {"day": "jueves"})
    assert calendar.calendar_args("partidos de copa cerca") == {"category": "clubs"}
    assert calendar.calendar_args("partidos destacados 2026-11-12") == {"day": "2026-11-12", "important": True}


def test_affirmative_keeps_list_context_and_filters(monkeypatch):
    client = FakeLLM([ToolCall("m", "get_upcoming_matches")], [TextDelta("Partidos consultados.")])
    out = {}
    events = list(
        orchestrator.run_chat(
            client,
            "si, busca eso",
            UserPreferences(),
            entities={"shown_ids": [99], "calendar_filters": {"important": True, "category": "international"}},
            consulted_entities=out,
        )
    )
    args = next(e.data["args"] for e in events if e.event == "tool_start")
    assert args["important"] and args["category"] == "international"
    assert out["shown_ids"] == [181043]
    assert events[-1].data["success"]


def test_calendar_empty_day_is_useful_verified_fallback():
    client = FakeLLM([ToolCall("m", "get_upcoming_matches", {"day": "jueves"})], [TextDelta("")])
    events = list(orchestrator.run_chat(client, "que partidos hay el jueves?", UserPreferences()))
    assert "jueves 12-11" in "".join(e.data["delta"] for e in events if e.event == "token")
    assert events[-1].data["success"]


def test_local_fields_date_only_and_missing():
    assert calendar.local_fields(None) == {"kickoff_local": None, "local_date": None, "weekday": None}
    assert calendar.local_fields("2026-11-13") == {
        "kickoff_local": None,
        "local_date": "2026-11-13",
        "weekday": "viernes",
    }


def test_categories_keep_official_senior_internationals(monkeypatch):
    matches = [MATCH, dict(MATCH, ref="m:2", league="UNL"), dict(MATCH, ref="m:3", league="E0")]
    monkeypatch.setattr(tools.service, "upcoming", lambda: matches)
    assert {m["match_id"] for m in tools.tool_get_upcoming_matches(category="international")} == {181043, 2}
    assert [m["match_id"] for m in tools.tool_get_upcoming_matches(category="clubs")] == [3]


def test_all_sse_payload_dates_use_local_sources():
    call = ToolCall("a", "get_upcoming_matches")
    data = tools.tool_get_upcoming_matches()
    message = orchestrator._tool_message(call, record(data, call.name), orchestrator.observe(record(data, call.name)))
    assert '"kickoff":' not in message["content"]
    assert '"local_date": "2026-11-13"' in message["content"]
    assert json.loads(message["content"])["data"][0]["weekday"] == "viernes"


def test_model_cannot_invent_day_on_nearby_calendar():
    client = FakeLLM(
        [ToolCall("m", "get_upcoming_matches", {"day": "hoy", "important": True})],
        [TextDelta("Calendario consultado.")],
    )
    events = list(orchestrator.run_chat(client, "que partidos de copa o ligas hay cerca?", UserPreferences()))
    args = next(e.data["args"] for e in events if e.event == "tool_start")
    assert args["day"] is None and args["important"] is False and args["category"] == "clubs"
    sent = client.messages[1][-2]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(sent)["day"] is None


def test_odds_question_requires_canonical_odds_status():
    wrong = "Colombia es favorito, con probabilidades de 67.5%."
    events = list(
        orchestrator.run_chat(
            FakeLLM([ToolCall("r", "request_odds", {"match_id": 181043})],
                    [TextDelta(wrong)], [TextDelta(wrong)]), "¿Y ese partido?", UserPreferences(), entities=ENTITY
        )
    )
    emitted = "".join(e.data["delta"] for e in events if e.event == "token")
    assert emitted == "Colombia vs Chile: sin cuotas de ninguna casa todavía."
    assert events[-1].data["success"]


@pytest.mark.parametrize("question", ["¿Cuál de esos?", "¿El primero a qué hora?", "¿Y Colombia?"])
def test_short_reference_to_previous_list(question):
    assert routing.is_follow_up(question, {"shown_ids": [181043]})
