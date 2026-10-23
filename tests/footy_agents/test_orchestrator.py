"""Pruebas del micro-orquestador, el cliente LLM y el endpoint SSE con un LLM simulado (sin red ni tokens)."""

import asyncio
import json
import sqlite3

import pytest
import requests

from footy_agents import llm, orchestrator, tools
from footy_agents.llm import LLMUnavailable, TextDelta, ToolCall
from footy_agents.schemas import ChatEvent, ChatRequest, UserPreferences
from footy_agents.web import router


class FakeLLM:
    """Responde con guiones fijos por iteración y guarda lo que recibió en cada llamada."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls: list[tuple[list[dict], list[dict] | None]] = []

    def stream_chat(self, messages, tools=None):
        self.calls.append(([dict(m) for m in messages], tools))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        yield from turn


def events(client, message="¿Qué partidos hay hoy?"):
    return list(orchestrator.run_chat(client, message, UserPreferences(favorite_teams=["Colo-Colo"])))


@pytest.fixture
def fake_tool(monkeypatch):
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "get_upcoming_matches",
                        lambda limit=10, league=None: [{"home": "Colo Colo", "away": "Everton"}])


def test_direct_answer_streams_tokens():
    out = events(FakeLLM([TextDelta("Hola, "), TextDelta("¿en qué te ayudo?")]))
    assert [e.event for e in out] == ["token", "token", "done"]
    assert out[-1].data == {"iterations": 1, "success": True}


def test_tool_loop_feeds_results_back(fake_tool):
    client = FakeLLM([ToolCall(id="c1", name="get_upcoming_matches", arguments={"limit": 1})],
                     [TextDelta("Hoy juega Colo Colo vs Everton.")])
    out = events(client)
    assert [e.event for e in out] == ["tool_start", "tool_result", "token", "done"]
    assert out[1].data["success"] is True and out[1].data["summary"] == "1 resultado(s)"
    assert out[-1].data == {"iterations": 2, "success": True}
    # la segunda llamada recibe la petición de herramienta y su resultado real
    second = client.calls[1][0]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "get_upcoming_matches"
    assert second[-1]["role"] == "tool" and "Everton" in second[-1]["content"]
    # el system prompt lleva las reglas anti-alucinación y las preferencias
    assert "NUNCA inventes" in client.calls[0][0][0]["content"] and "Colo-Colo" in client.calls[0][0][0]["content"]


def test_iteration_limit_last_call_without_tools(fake_tool):
    loop = [ToolCall(id="c", name="get_upcoming_matches")]
    client = FakeLLM(loop, loop, loop, [TextDelta("Respuesta final.")])
    out = events(client)
    assert len(client.calls) == orchestrator.MAX_ITERATIONS
    assert all(tools for _, tools in client.calls[:-1]) and client.calls[-1][1] is None
    assert out[-1].data == {"iterations": 4, "success": True}


def test_model_insists_on_tools_is_cut(fake_tool):
    loop = [ToolCall(id="c", name="get_upcoming_matches")]
    out = events(FakeLLM(loop, loop, loop, loop))
    assert out[-2].event == "error" and out[-1].data == {"iterations": 4, "success": False}


def test_ollama_down_degrades_gracefully():
    out = events(FakeLLM(LLMUnavailable("connection refused")))
    assert [e.event for e in out] == ["token", "done"]
    assert "no está disponible" in out[0].data["delta"]
    assert out[1].data["success"] is False


def test_invalid_tool_arguments_reported_to_model():
    client = FakeLLM([ToolCall(id="c1", name="get_league_standings", raw_arguments="{liga: CHL")],
                     [TextDelta("No pude consultar la tabla.")])
    out = events(client)
    assert out[1].data["success"] is False and "JSON" in out[1].data["summary"]


def test_empty_answer_is_error():
    out = events(FakeLLM([]))
    assert [e.event for e in out] == ["error", "done"]


def test_sse_format():
    sse = ChatEvent(event="token", data={"delta": "ñ"}).to_sse()
    assert sse == 'event: token\ndata: {"delta": "ñ"}\n\n'


class FakeResponse:
    def __init__(self, lines):
        self.lines = lines

    def raise_for_status(self):
        pass

    def iter_lines(self, decode_unicode=True):
        yield from self.lines

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _chunk(delta):
    return "data: " + json.dumps({"choices": [{"delta": delta}]})


def test_client_parses_openai_stream(monkeypatch):
    """Texto en streaming y llamadas a herramientas en trozos (formato OpenAI) o completas (Ollama)."""
    lines = [
        _chunk({"content": "Hola"}),
        "",
        _chunk({"tool_calls": [{"index": 0, "id": "a",
                                "function": {"name": "get_value_bets", "arguments": '{"min_'}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'edge": 0.08}'}}]}),
        _chunk({"tool_calls": [{"index": 1, "id": "b", "function": {"name": "get_system_performance",
                                                                   "arguments": "{}"}}]}),
        "data: [DONE]",
    ]
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResponse(lines))
    out = list(llm.OpenAICompatibleClient("http://x/v1", "m").stream_chat([], None))
    assert out == [TextDelta("Hola"), ToolCall(id="a", name="get_value_bets", arguments={"min_edge": 0.08}),
                   ToolCall(id="b", name="get_system_performance", arguments={})]


def test_client_connection_error_is_unavailable(monkeypatch):
    def refuse(*_a, **_k):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(llm.requests, "post", refuse)
    with pytest.raises(LLMUnavailable):
        list(llm.OpenAICompatibleClient("http://x/v1", "m").stream_chat([]))


def test_chat_endpoint_streams_sse(monkeypatch):
    def memory_db():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(router, "connect", memory_db)
    resp = router.chat(ChatRequest(message="hola"), client=FakeLLM([TextDelta("¡Hola!")]))
    assert resp.media_type == "text/event-stream"

    async def collect():
        return [chunk async for chunk in resp.body_iterator]
    body = "".join(asyncio.run(collect()))
    assert body.startswith("event: token\n") and "event: done" in body


def test_client_decodes_utf8_without_charset(monkeypatch):
    """Ollama no declara charset en text/event-stream: los acentos deben llegar intactos."""
    class Latin1Response(FakeResponse):
        encoding = "ISO-8859-1"

        def iter_lines(self, decode_unicode=True):
            for line in self.lines:
                raw = line.encode("utf-8")
                yield raw.decode(self.encoding)

    resp = Latin1Response([_chunk({"content": "División Ñuñoa"}), "data: [DONE]"])
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: resp)
    out = list(llm.OpenAICompatibleClient("http://x/v1", "m").stream_chat([]))
    assert out == [TextDelta("División Ñuñoa")]
