"""Salud HTTP: no inferencia, caché de éxitos/fallos y modelo configurado presente."""

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from footy_agents import health
from footy_agents.schemas import AgentHealth
from footy_agents.web.router import router


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


@pytest.fixture
def setup(monkeypatch):
    cfg = {"agents": {"llm": {"base_url": "http://local/v1/", "model": "model"},
                      "briefing": {"use_llm": False}}}
    monkeypatch.setattr(health.config, "settings", lambda: cfg)
    monkeypatch.setattr(health, "_cache", None)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield cfg, client


def test_health_http_cache_expiry_and_config_change(setup, monkeypatch):
    cfg, client = setup
    clock, calls = [100.0], []
    monkeypatch.setattr(health.time, "monotonic", lambda: clock[0])

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"data": [{"id": "model"}]})
    monkeypatch.setattr(health.requests, "get", get)
    response = client.get("/api/agent/health")
    assert response.status_code == 200
    assert response.json() == {"llm_available": True, "briefing_mode": "template", "model": "model",
                               "autostart": False, "startup_failed": False}
    clock[0] += 59
    assert client.get("/api/agent/health").json() == response.json()
    assert calls == [("http://local/v1/models", {"timeout": 1.0})]
    clock[0] += 1
    client.get("/api/agent/health")
    assert len(calls) == 2
    cfg["agents"]["briefing"]["use_llm"] = True
    assert client.get("/api/agent/health").json()["briefing_mode"] == "llm"
    assert len(calls) == 3


@pytest.mark.parametrize("failure", [requests.ConnectionError(), requests.Timeout(), requests.HTTPError()])
def test_unavailable_is_cached_and_never_propagates(setup, monkeypatch, failure):
    _, client = setup
    calls = []

    def get(*args, **kwargs):
        calls.append(1)
        raise failure
    monkeypatch.setattr(health.requests, "get", get)
    for _ in range(2):
        response = client.get("/api/agent/health")
        assert response.status_code == 200 and response.json()["llm_available"] is False
    assert calls == [1]


@pytest.mark.parametrize("payload", [{"data": [{"id": "other"}]}, {"data": None}, [], ValueError("JSON")])
def test_missing_model_or_invalid_payload_is_unavailable(setup, monkeypatch, payload):
    _, client = setup
    monkeypatch.setattr(health.requests, "get", lambda *args, **kwargs: Response(payload))
    assert client.get("/api/agent/health").json()["llm_available"] is False


def test_health_schema_rejects_extra_fields():
    with pytest.raises(ValidationError):
        AgentHealth(llm_available=True, briefing_mode="template", model="m", extra=True)
