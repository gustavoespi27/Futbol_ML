"""Pruebas unitarias para las herramientas (tools) del agente."""

import pytest

from footy_agents import tools
from footy_agents.tool_args import TOOL_MODELS


def test_execute_unknown_tool():
    """Ejecutar una herramienta inexistente retorna un registro de error sin crashear."""
    res = tools.execute_tool("herramienta_fantasma", {})
    assert res.success is False
    assert "no registrada" in (res.error_message or "")
    assert res.result is None


def test_tool_get_upcoming_matches_mocked(monkeypatch):
    """Prueba la obtención condensada de partidos con mock de red/servicio."""
    mock_data = [
        {"ref": "m:10", "league": "CHL", "league_name": "Chile", "kickoff": "2026-10-23T20:00:00Z",
         "home": "Colo-Colo", "away": "U. de Chile", "pro": [{"bet": True}], "recommendation": {"text": "Apostar"}},
        {"ref": "m:11", "league": "ARG", "league_name": "Argentina", "kickoff": "2026-10-23T22:00:00Z",
         "home": "Boca", "away": "River", "pro": [], "recommendation": {"text": "No apostar"}}
    ]
    monkeypatch.setattr("footy.web.service.upcoming", lambda: mock_data)

    record = tools.execute_tool("get_upcoming_matches", {"limit": 1})
    assert record.success is True
    assert len(record.result) == 1
    assert record.result[0]["home"] == "Colo-Colo"
    assert record.result[0]["has_pinnacle_price"] is True


def test_tool_get_value_bets_mocked(monkeypatch):
    """Prueba el filtrado de apuestas de valor según el umbral de edge."""
    mock_sugg = {
        "singles": [
            {"match": 10, "home": "Colo-Colo", "away": "U. de Chile", "league": "CHL",
             "label": "Gana local", "book": "Bet365", "odds": 2.10, "fair_odds": 1.923, "edge": 0.08, "stake": 0.02,
             "reason": "Edge +8%"},
            {"match": 11, "home": "Boca", "away": "River", "league": "ARG",
             "label": "Empate", "book": "Bet365", "odds": 3.40, "fair_odds": 3.17, "edge": 0.07, "stake": 0.01,
             "reason": "Edge +7%"}
        ]
    }
    monkeypatch.setattr("footy.web.service.upcoming", lambda: [])
    monkeypatch.setattr("footy.web.service.current_suggestions", lambda _: mock_sugg)

    record = tools.execute_tool("get_value_bets", {"min_edge": 0.075})
    assert record.success is True
    assert len(record.result) == 1
    assert record.result[0]["home"] == "Colo-Colo"
    assert record.result[0]["edge"] == 0.08
    assert record.result[0]["fair_odds"] == 1.92


def test_tool_simulate_match_mocked(monkeypatch):
    """Prueba la simulación con datos simulados del motor predictivo."""
    mock_pred = {
        "league": "CHL", "home": "Colo-Colo", "away": "Everton",
        "xg": [1.85, 0.95], "p_model": [0.60, 0.25, 0.15],
        "top_scores": [["2-0", 0.12], ["1-0", 0.11]],
    }
    monkeypatch.setattr("footy.web.service.predict", lambda *args, **kwargs: mock_pred)
    monkeypatch.setattr(tools.service, "teams", lambda code: ROSTER)
    monkeypatch.setattr(tools, "load_params", lambda: {"CHL": {}})

    record = tools.execute_tool("simulate_match", {
        "league": "CHL", "home_team": "Colo-Colo", "away_team": "Everton"
    })
    assert record.success is True
    assert record.result["home"] == "Colo-Colo"
    assert record.result["expected_goals"]["home"] == 1.85
    assert record.result["probabilities_1x2"]["home_win"] == "60.0%"
    assert record.result["top_scores"][0] == {"score": "2-0", "probability": "12.0%"}


ROSTER = [{"id": 1, "name": "Colo-Colo"}, {"id": 2, "name": "Everton"}, {"id": 3, "name": "Universidad de Chile"},
          {"id": 4, "name": "Universidad de Concepcion"}]


def test_simulate_without_league_model_uses_cross_league(monkeypatch):
    captured = []

    def cross(home_league, away_league, home_id, away_id, odds):
        captured.append((home_league, away_league, home_id, away_id))
        return {"home": "Colo-Colo", "away": "Universidad de Chile", "source": "modelo entre ligas",
                "xg": [1.69, 0.99], "p_model": [.5369, .2414, .2216], "top_scores": [["1-0", .1158]]}
    monkeypatch.setattr(tools.service, "teams", lambda code: ROSTER)
    monkeypatch.setattr(tools.service, "predict_cross", cross)
    monkeypatch.setattr(tools, "load_params", lambda: {})
    result = tools.tool_simulate_match("CHL", "el colo", "la u")
    assert captured == [("CHL", "CHL", 1, 3)]
    assert result["model"] == "modelo entre ligas" and result["probabilities_1x2"]["home_win"] == "53.7%"
    with pytest.raises(KeyError, match="no encontrado"):
        tools.tool_simulate_match("CHL", "Colo-Colo", "Universidad")      # parcial ambiguo: no adivina



def test_tool_league_standings_mocked(monkeypatch):
    """La tabla de footy.web.service.standings viene en 'rows'; sin tabla devuelve un error explícito."""
    rows = [{"pos": i, "team_id": i, "name": f"Equipo {i}", "played": 10, "points": 30 - i, "gd": 5 - i,
             "recent": ["W", "D"]} for i in range(1, 11)]
    monkeypatch.setattr("footy.web.service.standings",
                        lambda code: {"league": code, "league_name": "Chile", "season": "2026", "rows": rows}
                        if code == "CHL" else None)

    record = tools.execute_tool("get_league_standings", {"league": "CHL"})
    assert record.success is True
    assert len(record.result["top_standings"]) == 8
    assert record.result["top_standings"][0]["team"] == "Equipo 1"
    assert "Códigos cercanos" in tools.execute_tool("get_league_standings", {"league": "XXX"}).error_message


def test_tool_failure_is_recorded(monkeypatch):
    """Si el motor lanza un error, el dispatcher lo registra en vez de propagarlo."""
    def boom(*_args):
        raise KeyError("Equipo desconocido")
    monkeypatch.setattr("footy.web.service.predict", boom)
    monkeypatch.setattr(tools.service, "teams", lambda code: [{"id": 1, "name": "X"}, {"id": 2, "name": "Y"}])
    monkeypatch.setattr(tools, "load_params", lambda: {"CHL": {}})

    record = tools.execute_tool("simulate_match", {"league": "CHL", "home_team": "X", "away_team": "Y"})
    assert record.success is False
    assert "Equipo desconocido" in (record.error_message or "")


def test_tools_spec_matches_registry():
    """Cada herramienta anunciada al LLM existe en el registro y viceversa."""
    assert {t["function"]["name"] for t in tools.OPENAI_TOOLS_SPEC} == set(tools.TOOLS_REGISTRY)
    for spec in tools.OPENAI_TOOLS_SPEC:
        function = spec["function"]
        assert function["parameters"] == TOOL_MODELS[function["name"]].model_json_schema()


@pytest.mark.parametrize("name,args", [
    ("get_upcoming_matches", {"limit": 21}), ("get_upcoming_matches", {"limit": "5"}),
    ("get_value_bets", {"min_edge": float("nan")}),
    ("simulate_match", {"league": "PL", "home_team": "A"}),
    ("get_league_standings", {"league": 20}), ("get_system_performance", {"extra": True}),
])
def test_invalid_arguments_never_execute(name, args, monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("No debe ejecutar argumentos inválidos")
    monkeypatch.setitem(tools.TOOLS_REGISTRY, name, forbidden)
    result = tools.execute_tool(name, args)
    assert not result.success and "Argumentos inválidos" in result.error_message


def test_upcoming_by_team_with_probabilities(monkeypatch):
    """Filtro por equipo tolerante a guiones y probabilidades oficiales como porcentaje."""
    monkeypatch.setattr("footy.web.service.upcoming", lambda: [
        {"ref": "m:1", "league": "CHL", "home": "Palestino", "away": "Colo Colo", "kickoff": "2026-10-24T20:00:00Z",
         "p_official": [0.25, 0.27, 0.48], "source": "modelo"},
        {"ref": "m:2", "league": "CHL", "home": "Everton", "away": "Cobresal", "kickoff": "2026-10-24T22:00:00Z"},
    ])
    record = tools.execute_tool("get_upcoming_matches", {"team": "Colo-Colo"})
    assert [m["match_id"] for m in record.result] == [1]
    probs = record.result[0]["probabilities_1x2"]
    assert (probs["home_win"], probs["draw"], probs["away_win"]) == ("25.0%", "27.0%", "48.0%")
    assert probs["favorite"] == "Colo Colo" and probs["away_team"] == "Colo Colo"
    assert record.result[0]["probability_source"] == "modelo"


def test_system_performance_as_percentages(monkeypatch):
    monkeypatch.setattr("footy.web.service.overview", lambda: {
        "model_version": "v3", "tracking": {"evaluated": 361, "hit_rate": 0.5319, "bets_yield": -0.0739,
                                            "bets_clv": -0.0303, "ll_market": 0.9622}})
    tracking = tools.execute_tool("get_system_performance", {}).result["tracking"]
    assert tracking == {"evaluated": 361, "hit_rate": "53.2%", "bets_yield": "-7.4%", "bets_clv": "-3.0%",
                        "ll_market": 0.9622}
