"""Las pruebas del agente no leen el calendario local ni su base de datos."""

import pytest

from footy_agents import orchestrator, tools


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch):
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda message: None)
    monkeypatch.setattr(tools.service, "league_catalog", lambda: [
        {"code": "CHL", "name": "Primera División de Chile"},
        {"code": "E0", "name": "Premier League"}, {"code": "SP1", "name": "La Liga"},
    ])
