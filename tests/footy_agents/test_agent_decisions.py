"""Decisiones del agente: observaciones tipadas, desvíos, recuperación y reparación (FakeLLM, sin red)."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from footy_agents import orchestrator, tools
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.observations import observe
from footy_agents.schemas import ToolCallRecord, UserPreferences


class FakeLLM:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []

    def stream_chat(self, messages, tools=None):
        self.calls.append(([dict(m) for m in messages], tools))
        yield from self.turns.pop(0)


def run(client, message="¿Cómo llega el Colo?"):
    return list(orchestrator.run_chat(client, message, UserPreferences()))


def steps(events):
    return [(e.data["kind"], e.data["text"]) for e in events if e.event == "step"]


def answer(events):
    return "".join(e.data["delta"] for e in events if e.event == "token")


def iso(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


MATCHES = [
    {"ref": "m:10", "league": "CHL", "league_name": "Primera División", "kickoff": iso(20), "home": "Colo Colo",
     "away": "Everton", "source": "ML", "p_official": [.5, .3, .2], "xg": [1.4, .9], "over25": .45, "btts": .5,
     "top_scores": [["1-0", .12]], "pro": []},
    {"ref": "m:11", "league": "E0", "league_name": "Premier League", "kickoff": iso(30), "home": "Arsenal",
     "away": "Chelsea", "source": "mercado", "p_official": [.55, .25, .2], "xg": [1.6, 1.0],
     "pro": [{"key": "1", "odds": 2.1, "book": "Bet365", "fair_odds": 1.9, "edge": .08, "bet": True},
             {"key": "2", "odds": 4.0, "book": "Bet365", "fair_odds": 4.4, "edge": -.05, "bet": False}]},
    {"ref": "m:12", "league": "CHL", "league_name": "Primera División", "kickoff": iso(-1), "home": "Cobresal",
     "away": "Huachipato", "source": "ML", "p_official": [.4, .3, .3], "pro": []},
]


@pytest.fixture
def calendar(monkeypatch):
    def database():
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT)")
        db.executemany("INSERT INTO teams (name) VALUES (?)",
                       [("Colo Colo",), ("Universidad de Chile",), ("Chile",), ("Everton",), ("Everton de Viña",)])
        return db

    monkeypatch.setattr(tools.service, "upcoming", lambda: MATCHES)
    monkeypatch.setattr(tools, "connect", database)


def record(name, result=None, success=True, args=None, error=None):
    return ToolCallRecord(tool_name=name, arguments=args or {}, result=result, success=success,
                          execution_time_ms=1.0, error_message=error)


# --- observaciones --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rec,status,options", [
    (record("get_upcoming_matches", [], args={"team": "Colito"}), "not_found", ["find_team"]),
    (record("get_upcoming_matches", []), "empty", ["get_coverage"]),
    (record("get_upcoming_matches", [{"has_pinnacle_price": False}]), "no_pinnacle", ["analyze_match", "get_coverage"]),
    (record("get_upcoming_matches", [{"has_pinnacle_price": True}]), "ok", []),
    (record("get_value_bets", []), "empty", ["get_coverage"]),
    (record("find_team", []), "not_found", []),
    (record("find_team", [{"team": "A", "exact": False}, {"team": "B", "exact": False}]), "ambiguous",
     ["analyze_match"]),
    (record("find_team", [{"team": "A", "exact": True, "next_match": {"match_id": 1}},
                          {"team": "AB", "exact": False}]), "ok", ["analyze_match", "get_team_form"]),
    (record("find_team", [{"team": "A", "exact": True, "next_match": None}]), "ok", ["get_team_form"]),
    (record("get_team_form", None, success=False, error="Equipo no encontrado"), "not_found", ["find_team"]),
    (record("analyze_match", {"status": "started"}), "started", ["get_upcoming_matches"]),
    (record("analyze_match", {"status": "no_pinnacle"}), "no_pinnacle", ["get_coverage"]),
    (record("analyze_match", None, success=False, error="no está"), "not_found",
     ["find_team", "get_upcoming_matches"]),
    (record("simulate_match", None, success=False, error="'Equipo X no encontrado'"), "not_found", ["find_team"]),
    (record("get_league_standings", None, success=False, error="Liga no reconocida: X"), "not_found", []),
    (record("get_coverage", {"stale": True}), "stale_data", []),
    (record("get_system_performance", {"x": 1}), "ok", []),
])
def test_observation_classifies_results(rec, status, options):
    obs = observe(rec)
    assert obs.status == status and obs.options == options
    assert not any(ch.isdigit() for ch in obs.note)      # las notas no aportan cifras citables


# --- herramientas nuevas -----------------------------------------------------------------------------------------

def test_find_team_prefers_exact_and_upcoming(calendar):
    rows = tools.tool_find_team("colo colo")
    assert rows[0]["team"] == "Colo Colo" and rows[0]["exact"] and rows[0]["next_match"]["match_id"] == 10
    everton = tools.tool_find_team("everton")
    assert everton[0]["team"] == "Everton" and everton[0]["next_match"] is not None
    assert {r["team"] for r in tools.tool_find_team("chile")} == {"Chile", "Universidad de Chile"}
    assert tools.tool_find_team("zzzz") == []


def test_analyze_match_statuses(calendar):
    assert tools.tool_analyze_match(10)["status"] == "no_pinnacle"
    assert tools.tool_analyze_match(12)["status"] == "started"
    priced = tools.tool_analyze_match(11)
    assert priced["status"] == "ok" and priced["value_status"] == "con_ventaja"
    assert priced["value_selections"] == [{"selection": "Arsenal", "best_odds": 2.1, "bookmaker": "Bet365",
                                           "pinnacle_fair_odds": 1.9, "edge": "8.0%"}]
    with pytest.raises(ValueError):
        tools.tool_analyze_match(999)


@pytest.mark.parametrize("hours,stale", [(-2, False), (-40, True)])
def test_coverage_reports_freshness(calendar, monkeypatch, hours, stale):
    monkeypatch.setattr(tools.service, "overview", lambda: {"last_daily_run": iso(hours)})
    cov = tools.tool_get_coverage()
    assert cov["stale"] is stale
    assert (cov["upcoming_matches"], cov["with_pinnacle_price"]) == (3, 1)
    assert cov["next_with_pinnacle"]["match_id"] == 11


# --- desvíos del orquestador ----------------------------------------------------------------------------------------

def test_deviation_after_not_found(calendar):
    client = FakeLLM([ToolCall(id="a", name="get_upcoming_matches", arguments={"team": "el Colo"})],
                     [ToolCall(id="b", name="find_team", arguments={"name": "Colo"})],
                     [ToolCall(id="c", name="analyze_match", arguments={"match_id": 10})],
                     [TextDelta("Colo Colo es favorito con 50.0% según el modelo; sin precio de Pinnacle.")])
    events = run(client)
    kinds = [k for k, _ in steps(events)]
    assert kinds == ["observation", "deviation", "observation"]
    order = [e.event if e.event != "step" else e.data["kind"] for e in events]
    assert order.index("deviation") < order.index("tool_start", order.index("deviation"))
    assert events[-1].data["success"] is True
    # el modelo recibe la observación tipada, no solo los datos
    assert '"status": "not_found"' in client.calls[1][0][-1]["content"]


def test_recovery_when_model_gives_up(calendar):
    client = FakeLLM([ToolCall(id="a", name="get_upcoming_matches", arguments={"team": "el Colo"})],
                     [TextDelta("No encontré partidos.")],
                     [ToolCall(id="b", name="find_team", arguments={"name": "Colo"})],
                     [TextDelta("Colo Colo juega contra Everton.")])
    events = run(client)
    assert [k for k, _ in steps(events)] == ["observation", "recovery", "deviation"]
    assert answer(events) == "Colo Colo juega contra Everton."
    assert "No encontré" not in answer(events)


def test_recovery_only_once(calendar):
    client = FakeLLM([ToolCall(id="a", name="get_upcoming_matches", arguments={"team": "el Colo"})],
                     [TextDelta("No encontré partidos.")], [TextDelta("Sigo sin encontrarlo.")])
    events = run(client)
    assert answer(events) == "Sigo sin encontrarlo." and events[-1].data["success"] is True
    assert len(client.calls) == 3


def test_repair_rewrites_unsupported_numbers(calendar):
    client = FakeLLM([ToolCall(id="a", name="analyze_match", arguments={"match_id": 10})],
                     [TextDelta("Colo Colo gana con 73.0%.")],
                     [TextDelta("Colo Colo gana con 50.0% según el modelo.")])
    events = run(client, "Analiza el partido")
    assert [k for k, _ in steps(events)] == ["observation", "repair"]
    assert answer(events) == "Colo Colo gana con 50.0% según el modelo."
    assert events[-1].data == {"iterations": 3, "success": True}
    assert "73.0%" in client.calls[-1][0][-1]["content"]       # el modelo sabe qué cifra quitar o reconsultar
    assert client.calls[-1][1] is not None                     # puede volver a consultar en vez de solo borrar


def test_steps_are_serialized_for_sse():
    event = orchestrator._step("deviation", "Cambio de camino")
    assert event.to_sse() == 'event: step\ndata: {"kind": "deviation", "text": "Cambio de camino"}\n\n'


def test_find_team_resolves_nicknames(calendar):
    assert tools.tool_find_team("la roja")[0]["team"] == "Chile"
    assert tools.tool_find_team("El Colo")[0]["team"] == "Colo Colo"


def test_team_form_summarizes_profile(calendar, monkeypatch):
    profile = {"name": "Colo Colo", "league_name": "Primera División",
               "standing": {"pos": 1, "teams": 16, "points": 57, "played": 25, "won": 18, "drawn": 3, "lost": 4,
                            "gf": 52, "ga": 28, "season": "2026"},
               "recent": [{"outcome": o, "score": [1, 0], "opponent": f"R{i}", "is_home": True,
                           "date": f"2026-10-0{i}T20:00:00Z", "league_name": "Primera División"}
                          for i, o in enumerate("LWDWWW", start=1)],
               "season": {"gf_pg": 2.12, "ga_pg": 1.08, "played": 26}, "upcoming": []}
    monkeypatch.setattr(tools.service, "team_profile", lambda team_id: profile)
    form = tools.tool_get_team_form("el colo")
    assert form["form_last5"] == "GEGGG" and form["standing"]["pos"] == 1 and "season" not in form["standing"]
    assert form["last_results"][0] == {"local_date": "2026-10-02", "weekday": "viernes",
                                       "kickoff_local": "vie 02-10, 17:00 hora de Chile", "opponent": "R2",
                                       "home": True, "score": "1-0",
                                       "result": "G", "competition": "Primera División"}
    with pytest.raises(ValueError, match="find_team"):
        tools.tool_get_team_form("Colito")


def test_freshness_text(calendar, monkeypatch):
    monkeypatch.setattr(tools.service, "overview", lambda: {"last_daily_run": iso(-5.5)})
    assert tools.tool_get_coverage()["freshness"] == "actualizado hace 5 horas"


def test_time_of_day_does_not_ground_loose_numbers():
    from footy_agents.grounding import verify_numbers
    rec = record("get_coverage", {"last_update": "2026-11-09T21:04:44Z"})
    assert not verify_numbers("Actualizado hace 4 horas", [rec]).verified
    assert verify_numbers("Actualizado el 9 de noviembre de 2026", [rec]).verified


@pytest.mark.parametrize("message", ["Dame una combinada segura para hoy", "¿Cuál es la apuesta más segura?",
                                     "pasame la fija del finde"])
def test_safe_bet_premise_is_rejected_without_llm(message):
    client = FakeLLM()
    events = run(client, message)
    assert client.calls == [] and steps(events)[0][0] == "policy"
    assert answer(events).startswith("No existen apuestas ni combinadas seguras")
    assert events[-1].data == {"iterations": 0, "success": True}


def test_safe_word_in_other_context_reaches_model():
    events = run(FakeLLM([TextDelta("Sí, los datos son seguros.")]), "¿Es seguro usar el panel?")
    assert answer(events) == "Sí, los datos son seguros."


def test_recovery_when_model_asks_instead_of_searching(calendar):
    client = FakeLLM([TextDelta("Primero, necesito el nombre completo del equipo.")],
                     [ToolCall(id="a", name="find_team", arguments={"name": "la roja"})],
                     [TextDelta("Chile no tiene partido próximo.")])
    events = run(client, "Analiza el partido de la roja")
    assert [k for k, _ in steps(events)][0] == "recovery"
    assert answer(events) == "Chile no tiene partido próximo."


def test_nickname_preloads_calendar(calendar, monkeypatch):
    monkeypatch.setattr(orchestrator, "upcoming_focus", tools.upcoming_focus)
    assert tools.upcoming_focus("Analiza el partido del cacique") == {"team": "Colo Colo", "limit": tools.MAX_MATCHES}


def test_numbered_lists_are_not_figures():
    from footy_agents.grounding import verify_numbers
    rec = record("get_upcoming_matches", [{"home": "Qatar U23", "kickoff": "2026-11-10T08:00:00Z"}])
    listing = "Próximos:\n1. Qatar U23 vs Singapore U23 el 10 de noviembre.\n2) Vietnam vs Thailand."
    assert verify_numbers(listing, [rec]).verified
    assert not verify_numbers("Hay 7 partidos.", [rec]).verified


def test_tool_mention_is_trimmed_not_rejected():
    useful = "No hay apuestas con valor: ninguna selección supera la ventaja mínima frente a Pinnacle."
    client = FakeLLM([ToolCall(id="a", name="get_value_bets", arguments={})],
                     [TextDelta(useful + " Puedes consultar la cobertura con get_coverage.")])
    events = run(client, "¿Qué apuestas con valor hay hoy?")
    assert answer(events) == useful and events[-1].data["success"] is True
    assert len(client.calls) == 2


def test_domain_claim_without_tools_triggers_consultation(calendar, monkeypatch):
    monkeypatch.setattr(tools.service, "overview", lambda: {"last_daily_run": iso(-1)})
    client = FakeLLM([TextDelta("Los datos están atrasados, por eso no hay apuestas.")],
                     [ToolCall(id="a", name="get_coverage", arguments={})],
                     [TextDelta("Ningún partido tiene precio de Pinnacle; los datos están al día.")])
    events = run(client, "¿Por qué no hay apuestas recomendadas?")
    assert [k for k, _ in steps(events)] == ["recovery"]
    assert "atrasados" not in answer(events) and events[-1].data["success"] is True
    assert "get_coverage" in client.calls[1][0][-1]["content"]


def test_probabilities_are_labeled_with_team_names():
    p = tools.labeled_1x2("Colombia", "Chile", [.675, .2, .125])
    assert p["favorite"] == "Colombia" and p["summary"] == "Colombia 67.5% · empate 20.0% · Chile 12.5%"
    assert tools.labeled_1x2("A", "B", [.3, .4, .3])["favorite"].startswith("ninguno")


def test_find_team_includes_next_match_favorite(calendar):
    nxt = tools.tool_find_team("colo colo")[0]["next_match"]
    assert nxt["probabilities_1x2"]["favorite"] == "Colo Colo"


def test_performance_claim_without_tools_is_consulted():
    client = FakeLLM([TextDelta("El rendimiento del sistema es bueno.")],
                     [TextDelta("Consulté y no tengo métricas.")])
    events = run(client, "¿Qué tan fiable es el sistema?")
    assert steps(events)[0][0] == "recovery"
