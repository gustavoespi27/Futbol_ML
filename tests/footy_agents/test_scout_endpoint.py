"""Contrato de lectura del Ojeador: límite validado, esquemas estrictos y sin red."""

import pytest
import test_odds_scout_cycle as cycle
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from footy.db.connection import connect
from footy_agents import odds_scout
from footy_agents.scout_schemas import ScoutDecision
from footy_agents.web import router


def test_scout_log_contract_and_bounds(tmp_path, monkeypatch):
    generator = cycle.db.__wrapped__(tmp_path)
    db = next(generator)
    try:
        result = odds_scout.run(db, cycle.NOW, budget=0)
        path = db.execute("PRAGMA database_list").fetchone()[2]
        monkeypatch.setattr(router, "connect", lambda: connect(path))
        app = FastAPI()
        app.include_router(router.router)
        with TestClient(app) as client:
            response = client.get("/api/agent/scout-log?limit=1")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1 and data[0]["id"] == result.id and data[0]["actions"] == 0
            assert data[0]["decisions"] and all("reason" in d for d in data[0]["decisions"])
            for limit in ("0", "101", "abc", "1.5"):
                assert client.get("/api/agent/scout-log", params={"limit": limit}).status_code == 422
        with pytest.raises(ValidationError):
            ScoutDecision(match_id=1, selected=True, source="espn", reason="x", unexpected=True)
    finally:
        generator.close()
