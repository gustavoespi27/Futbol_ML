"""Pruebas unitarias para las herramientas (tools) del agente."""

from agents import tools


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
    assert record.result[0]["has_odds"] is True


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

    record = tools.execute_tool("simulate_match", {
        "league": "CHL", "home_team": "Colo-Colo", "away_team": "Everton"
    })
    assert record.success is True
    assert record.result["home"] == "Colo-Colo"
    assert record.result["expected_goals"]["home"] == 1.85
    assert record.result["probabilities_1x2"]["home_win"] == 0.60



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
    assert "error" in tools.execute_tool("get_league_standings", {"league": "XXX"}).result


def test_tool_failure_is_recorded(monkeypatch):
    """Si el motor lanza un error, el dispatcher lo registra en vez de propagarlo."""
    def boom(*_args):
        raise KeyError("Equipo desconocido")
    monkeypatch.setattr("footy.web.service.predict", boom)

    record = tools.execute_tool("simulate_match", {"league": "CHL", "home_team": "X", "away_team": "Y"})
    assert record.success is False
    assert "Equipo desconocido" in (record.error_message or "")


def test_tools_spec_matches_registry():
    """Cada herramienta anunciada al LLM existe en el registro y viceversa."""
    assert {t["function"]["name"] for t in tools.OPENAI_TOOLS_SPEC} == set(tools.TOOLS_REGISTRY)
