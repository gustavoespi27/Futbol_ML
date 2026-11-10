"""P0-5 (ligas por nombre, país o gentilicio; retomar «chl») y P0-6 (simulación entre ligas y ambigüedad)."""

import pytest

from footy_agents import orchestrator, tools
from footy_agents.llm import TextDelta
from footy_agents.routing import intent_route
from footy_agents.schemas import UserPreferences

CATALOG = [
    {"code": "CHL", "name": "Primera División de Chile", "country": "Chile", "type": "league"},
    {"code": "E0", "name": "Premier League", "country": "Inglaterra", "type": "league"},
    {"code": "E1", "name": "Championship", "country": "Inglaterra", "type": "league"},
    {"code": "SP1", "name": "La Liga", "country": "España", "type": "league"},
    {"code": "UCL", "name": "UEFA Champions League", "country": "Copas UEFA", "type": "cup"},
]
TEAMS = [{"id": 93, "name": "Colo Colo", "league": "CHL", "n": 26},
         {"id": 850, "name": "Barcelona", "league": "SP1", "n": 38},
         {"id": 900, "name": "Real Madrid", "league": "SP1", "n": 38},
         {"id": 901, "name": "Real Salt Lake", "league": "USA", "n": 34}]


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setattr(tools.service, "league_catalog", lambda: CATALOG)
    monkeypatch.setattr(tools, "settings", lambda: {"competitions": {"CHL": {}, "E0": {}, "E1": {}, "SP1": {}}})
    monkeypatch.setattr(tools, "_active_league_teams", lambda: TEAMS)
    monkeypatch.setattr(tools, "league_names", lambda: {r["code"]: r["name"] for r in CATALOG} | {"USA": "MLS"})


@pytest.mark.parametrize("text, code", [
    ("la liga chilena", "CHL"), ("chile", "CHL"), ("liga de chile", "CHL"), ("primera de chile", "CHL"),
    ("CHL", "CHL"), ("chl", "CHL"), ("premier", "E0"), ("la inglesa", "E0"), ("la liga", "SP1"),
    ("la liga española", "SP1"), ("champions", "UCL"),
])
def test_league_by_name_country_or_demonym(text, code):
    assert tools.resolve_league(text) == code


def test_unknown_league_lists_code_and_name():
    with pytest.raises(ValueError, match=r"Códigos cercanos: CHL \(Primera División de Chile\)"):
        tools.resolve_league("Chil")


def test_standings_route_reads_the_league_from_the_sentence():
    assert intent_route("¿Cómo va la tabla de la liga chilena?", None) == ("get_league_standings", {"league": "CHL"})
    assert intent_route("¿cómo va la tabla?", None) == ("get_league_standings", {})


def test_short_league_reply_resumes_previous_question():
    history = [{"role": "user", "content": "quiero saber cómo va la tabla"},
               {"role": "assistant", "content": "¿De qué liga quieres la tabla? Puedes darme su código."}]
    assert orchestrator.league_reply("chl", history) == ("quiero saber cómo va la tabla (liga CHL)", "CHL")
    assert orchestrator.league_reply("chl", []) is None
    assert orchestrator.league_reply("¿qué partidos hay hoy en la premier?", history) is None


def test_cross_league_simulation_uses_cross_model(monkeypatch):
    captured = []

    def cross(home_league, away_league, home_id, away_id, odds):
        captured.append((home_league, away_league, home_id, away_id))
        return {"home": "Colo Colo", "away": "Barcelona", "source": "modelo entre ligas", "xg": [0.85, 2.61],
                "p_model": [.0993, .151, .7497], "top_scores": [["0-2", .12]]}
    monkeypatch.setattr(tools.service, "teams", lambda code: [{"id": 93, "name": "Colo Colo"}])
    monkeypatch.setattr(tools.service, "predict_cross", cross)
    monkeypatch.setattr(tools, "load_params", lambda: {"SP1": {}})
    result = tools.tool_simulate_match("CHL", "Colo Colo", "Barcelona")     # la liga es pista, no obligación
    assert captured == [("CHL", "SP1", 93, 850)]
    assert result["home_league"] == "CHL" and result["away_league"] == "SP1" and "Cruce entre ligas" in result["note"]
    assert result["probabilities_1x2"]["away_win"] == "75.0%"
    assert tools.tool_simulate_match(home_team="Colo Colo", away_team="Barcelona")["away_league"] == "SP1"


def test_ambiguous_club_asks_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(tools.service, "predict_cross", lambda *a: pytest.fail("no debe simular con ambigüedad"))
    result = tools.tool_simulate_match(home_team="Colo Colo", away_team="Real")
    assert result["status"] == "ambiguous"
    assert [o["team"] for o in result["options"]] == ["Real Madrid", "Real Salt Lake"]
    record = tools.execute_tool("simulate_match", {"home_team": "Colo Colo", "away_team": "Real"})
    from footy_agents.observations import observe
    assert observe(record).status == "ambiguous"
    with pytest.raises(KeyError, match="ninguna liga"):
        tools.tool_simulate_match(home_team="Colo Colo", away_team="Xyz FC")


class Recorder:
    def __init__(self, *turns):
        self.turns, self.calls = list(turns), []

    def stream_chat(self, messages, tools=None):
        self.calls.append(messages)
        yield from self.turns.pop(0)


def test_chat_suggestion_shows_the_chilean_table_without_llm(monkeypatch):
    monkeypatch.setattr(tools.service, "standings", lambda code: {
        "league_name": "Primera División de Chile", "season": "2026",
        "rows": [{"pos": 1, "name": "Colo Colo", "played": 25, "points": 57, "gd": 24, "recent": ["W"]}]})
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    client = Recorder()                                   # sin turnos: falla si se le pide una inferencia
    events = list(orchestrator.run_chat(client, "¿Cómo va la tabla de la liga chilena?", UserPreferences()))
    text = "".join(e.data["delta"] for e in events if e.event == "token")
    assert text.startswith("Primera División de Chile 2026") and "1. Colo Colo — 57 pts (25 PJ, DG +24)" in text
    assert client.calls == [] and events[-1].data["success"] is True


def test_hypothetical_matchup_routes_to_simulation_and_scheduled_to_analysis(monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [{"ref": "m:181043", "home": "Colombia", "away": "Chile"}])
    assert intent_route("¿quién ganaría Colo Colo contra el Barcelona de España?", None) == (
        "simulate_match", {"home_team": "colo colo", "away_team": "barcelona de espana"})
    assert intent_route("quién ganaría Colombia contra Chile", None) == ("analyze_match", {"match_id": 181043})
    assert tools.find_club("barcelona de espana")[0]["name"] == "Barcelona"


def test_clarification_completes_the_pending_simulation(monkeypatch):
    calls = []

    def cross(home_league, away_league, home_id, away_id, odds):
        calls.append((home_id, away_id))
        return {"home": "Colo Colo", "away": "Real Madrid", "source": "modelo entre ligas", "xg": [0.9, 2.3],
                "p_model": [.12, .18, .70], "top_scores": [["0-2", .11]]}
    monkeypatch.setattr(tools.service, "predict_cross", cross)
    monkeypatch.setattr(tools, "load_params", lambda: {})
    monkeypatch.setattr(tools.service, "upcoming", lambda: [])
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    first: dict = {}
    events = list(orchestrator.run_chat(Recorder(), "que pasa si juega colo colo vs el real?", UserPreferences(),
                                        consulted_entities=first))
    assert "Real Madrid (La Liga); Real Salt Lake (MLS)" in "".join(e.data["delta"] for e in events
                                                                   if e.event == "token")
    assert first["clarify"]["options"][0]["team"] == "Real Madrid"
    assert orchestrator.clarification_reply("qué partidos hay hoy", first) is None     # otro tema: no se secuestra
    assert orchestrator.clarification_reply("el segundo", first)[1] == "Real Salt Lake"
    client = Recorder([TextDelta("Real Madrid es favorito con 70%.")])
    events = list(orchestrator.run_chat(client, "real madrid", UserPreferences(), entities=first))
    assert calls == [(93, 900)]
    assert any(e.event == "step" and "Aclaración recibida: Real Madrid" in e.data["text"] for e in events)
    assert "".join(e.data["delta"] for e in events if e.event == "token") == "Real Madrid es favorito con 70%."


def test_table_follow_up_keeps_the_league_and_shows_the_bottom(monkeypatch):
    rows = [{"pos": i, "name": f"Equipo {i}", "played": 12, "points": 40 - i, "gd": 10 - i, "recent": []}
            for i in range(1, 21)]
    monkeypatch.setattr(tools.service, "standings", lambda code: {"league_name": "La Liga", "season": "2026",
                                                                 "rows": rows})
    monkeypatch.setattr(tools.service, "upcoming", lambda: [])
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    first: dict = {}
    list(orchestrator.run_chat(Recorder(), "¿cómo va la tabla de la liga española?", UserPreferences(),
                               consulted_entities=first))
    assert first["league"] == "SP1"
    assert intent_route("y cuáles son los últimos de la tabla?", first) == (
        "get_league_standings", {"league": "SP1", "part": "bottom"})
    client = Recorder()                                   # sin turnos: la tabla sale sin inferencia
    events = list(orchestrator.run_chat(client, "y cuáles son los últimos de la tabla?", UserPreferences(),
                                        entities=first))
    text = "".join(e.data["delta"] for e in events if e.event == "token")
    assert "últimos 6 de 20" in text and "20. Equipo 20" in text and "1. Equipo 1 " not in text
    assert client.calls == []


def test_hypothetical_phrasings_are_matchups_even_after_another_match(monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [{"ref": "m:181043", "home": "Colombia", "away": "Chile"}])
    previous = {"match_id": 181043, "home": "Colombia", "away": "Chile"}
    expected = ("simulate_match", {"home_team": "u de chile", "away_team": "barcelona"})
    assert intent_route("que pása si se enfrenta u de chile vs barcelona?", previous) == expected
    assert intent_route("no te pregunté por ese partido, te pregunté que si en el hipotético caso que se enfrente "
                        "u de chile vs barcelona cuáles son los porcentajes de cada uno", previous) == expected


def test_spanish_national_team_names_are_understood(monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [{"ref": "m:181001", "home": "Italy", "away": "France",
                                                             "league": "UNL"}])
    monkeypatch.setattr(tools.service, "league_catalog", lambda: [])
    assert tools.NICKNAMES["italia"] == "Italy" and tools.NICKNAMES["irlanda del norte"] == "Northern Ireland"
    assert tools.upcoming_focus("¿cuánto paga Italia contra Francia?")["team"] in {"Italy", "France"}
    assert tools.upcoming_focus("¿cuáles son los equipos más bajos de la tabla?") is None   # «bajos» ≠ Países Bajos


def test_team_form_route_never_leaves_the_team_to_the_model(monkeypatch):
    monkeypatch.setattr(tools.service, "upcoming", lambda: [{"ref": "m:181000", "home": "England", "away": "Croatia"}])
    monkeypatch.setattr(tools.service, "league_catalog", lambda: [])
    assert intent_route("¿cómo llega Inglaterra contra Croacia?", None) == ("analyze_match", {"match_id": 181000})
    assert intent_route("¿cómo llega Inglaterra?", None) == ("get_team_form", {"team": "England"})
    assert intent_route("como llega colo colo", None) == ("get_team_form", {"team": "Colo Colo"})


def test_favorite_league_by_demonym():
    assert intent_route("Añade la liga chilena a favoritos", None) == ("add_favorite", {"league": "CHL"})
