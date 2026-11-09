"""Contrato HTTP real del router, con SQLite aislado y LLM simulado."""

import json
import sqlite3
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from footy_agents import briefing_cache, tools
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.schemas import PersonalizedFeedResponse
from footy_agents.web import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "agent.sqlite"

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(router, "connect", connect)
    monkeypatch.setattr(briefing_cache, "connect", connect)
    monkeypatch.setattr(router.service, "get_personalized_feed", lambda *a, **k: PersonalizedFeedResponse(
        items=[], generated_at="2026-11-08T12:00:00Z", risk_profile="moderate",
        total_matches=0, favorite_matches_count=0))
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "get_system_performance", lambda: {"evaluados": 10})

    class FakeLLM:
        def stream_chat(self, messages, spec=None):
            if messages[-1]["role"] == "tool":
                yield TextDelta("Hay 10 partidos evaluados.")
            else:
                yield ToolCall(id="one", name="get_system_performance")

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router.router)
    app.dependency_overrides[router.get_llm_client] = FakeLLM
    with TestClient(app) as test_client:
        yield test_client


def sse(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [(block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:]))
            for block in response.text.strip().split("\n\n")]


def test_preferences_roundtrip_and_validation(client):
    assert client.get("/api/agent/preferences").json()["user_id"] == "default"
    response = client.put("/api/agent/preferences", json={"favorite_teams": ["Colo Colo"]})
    assert response.status_code == 200
    assert client.get("/api/agent/preferences").json()["favorite_teams"] == ["Colo Colo"]
    assert client.put("/api/agent/preferences", json={"risk_profile": "unlimited"}).status_code == 422
    assert client.put("/api/agent/preferences", json={"bankroll": 0}).status_code == 422


def test_feed_contract(client):
    response = client.get("/api/agent/feed")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_chat_tool_event_order(client):
    events = sse(client.post("/api/agent/chat", json={"message": "Rendimiento"}))
    assert [e[0] for e in events] == ["tool_start", "tool_result", "token", "done"]
    assert events[1][1]["success"] is True
    assert events[-1][1] == {"iterations": 2, "success": True}
    assert client.post("/api/agent/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/agent/chat", json={"message": "hola", "system": "otro"}).status_code == 422


def test_briefing_sse_template(client):
    events = sse(client.get("/api/agent/briefing"))
    assert [e[0] for e in events] == ["token", "done"]
    assert events[-1][1]["iterations"] == 0
