"""Memoria corta y bitácora de ejecuciones del agente (SQLite temporal, LLM simulado)."""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from footy_agents import memory
from footy_agents.llm import TextDelta
from footy_agents.schemas import ChatEvent, ChatRequest
from footy_agents.web import router


class FakeLLM:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []

    def stream_chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        yield from self.turns.pop(0)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "agent.sqlite"

    def connect():
        return sqlite3.connect(path)
    monkeypatch.setattr(router, "connect", connect)
    return connect


def chat(message, client):
    resp = router.chat(ChatRequest(message=message), client=client)

    async def collect():
        return "".join([chunk async for chunk in resp.body_iterator])
    return asyncio.run(collect())


def test_history_window_and_order(db):
    conn = db()
    memory.remember(conn, "u", "primera", "uno")
    memory.remember(conn, "u", "segunda", "dos")
    memory.remember(conn, "otro", "ajena", "x")
    assert [m["content"] for m in memory.history(conn, "u")] == ["primera", "uno", "segunda", "dos"]
    later = datetime.now(timezone.utc) + memory.MEMORY_WINDOW + timedelta(minutes=1)
    assert memory.history(conn, "u", now=later) == []
    memory.forget(conn, "u")
    assert memory.history(conn, "u") == [] and memory.history(conn, "otro")


def test_history_keeps_last_turns(db):
    conn = db()
    for i in range(memory.MEMORY_TURNS + 2):
        memory.remember(conn, "u", f"q{i}", f"a{i}")
    questions = [m["content"] for m in memory.history(conn, "u") if m["role"] == "user"]
    assert questions == [f"q{i}" for i in range(2, memory.MEMORY_TURNS + 2)]


def test_steps_summary():
    events = [ChatEvent(event="tool_start", data={"tool": "find_team", "args": {"name": "Colo"}}),
              ChatEvent(event="tool_result", data={"tool": "find_team", "success": True, "elapsed_ms": 3.0,
                                                   "summary": "1 resultado(s)"}),
              ChatEvent(event="step", data={"kind": "repair", "text": "Reescribe"}),
              ChatEvent(event="token", data={"delta": "Hola"}),
              ChatEvent(event="error", data={"error": "x"})]
    assert memory.steps_from(events) == [
        {"kind": "tool", "detail": "find_team", "args": {"name": "Colo"}, "success": True,
         "summary": "1 resultado(s)", "elapsed_ms": 3.0},
        {"kind": "repair", "detail": "Reescribe"}, {"kind": "error", "detail": "x"}]


def test_chat_remembers_verified_answers_and_logs_runs(db):
    first = FakeLLM([TextDelta("Hola, soy el asistente.")])
    assert "event: done" in chat("hola", first)
    second = FakeLLM([TextDelta("Sigo aquí.")])
    chat("¿y ahora?", second)
    sent = second.calls[0]
    assert [m["content"] for m in sent[1:]] == ["hola", "Hola, soy el asistente.", "¿y ahora?"]

    runs = router.runs(user_id="default", limit=5)
    assert [r.message for r in runs] == ["¿y ahora?", "hola"]
    assert runs[0].success and runs[0].iterations == 1 and runs[0].elapsed_ms >= 0
    assert runs[0].steps[0] == {"kind": "memory", "detail": "Último turno y entidades"}
    assert runs[1].steps[0] == {"kind": "memory", "detail": "Tema nuevo: sin historial ni entidades"}


def test_failed_answer_is_logged_but_not_remembered(db):
    invented = [TextDelta("La cuota es 9,99.")]
    chat("hola", FakeLLM(invented, invented, invented))
    run = router.runs(user_id="default", limit=1)[0]
    assert not run.success and [s["kind"] for s in run.steps] == ["memory", "recovery", "repair", "error"]
    assert memory.history(db(), "default") == []


def test_logging_failure_does_not_break_stream(monkeypatch):
    opened = []

    def connect():
        opened.append(True)
        if len(opened) > 1:                     # la conexión de la bitácora falla; la de preferencias no
            raise sqlite3.OperationalError("disco lleno")
        return sqlite3.connect(":memory:")
    monkeypatch.setattr(router, "connect", connect)
    body = chat("hola", FakeLLM([TextDelta("Hola.")]))
    assert "event: done" in body and len(opened) == 2
