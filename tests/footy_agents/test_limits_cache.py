"""Verifica ahorro de inferencia, invalidación por contenido y exclusión mutua."""

import json
from datetime import datetime, timezone

import pytest

from footy.db.connection import connect
from footy_agents import briefing_cache, llm, orchestrator
from footy_agents.llm import LLMBusy, TextDelta
from footy_agents.schemas import FeedItem, PersonalizedFeedResponse, UserPreferences


def test_cache_reuses_content_and_invalidates_preferences_and_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(briefing_cache, "connect", lambda: connect(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(briefing_cache.config, "settings", lambda: {"agents": {"briefing": {"use_llm": True}}})
    calls = []

    class Client:
        def stream_chat(self, messages, tools=None):
            calls.append(messages)
            yield TextDelta("Resumen.")

    # Tiempo futuro fijo relativo al reloj real para probar la ficha no vacía.
    kickoff = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    item = FeedItem(match_id=1, home_team="A", away_team="B", league="PL", kickoff=kickoff,
                    is_favorite_team=True, is_favorite_league=False, value_bets_count=0, relevance_score=1)
    monkeypatch.setattr(briefing_cache, "facts", lambda feed: {"contenido": [i.home_team for i in feed.items]})
    monkeypatch.setattr(briefing_cache, "run_briefing", lambda client, prefs, feed: iter([
        *[briefing_cache.ChatEvent(event="token", data={"delta": ev.text})
          for ev in client.stream_chat([])],
        briefing_cache.ChatEvent(event="done", data={"iterations": 1, "success": True})]))
    feed = PersonalizedFeedResponse(items=[item], generated_at="a", risk_profile="moderate",
                                    total_matches=1, favorite_matches_count=1)
    prefs = UserPreferences()
    first = list(briefing_cache.cached_briefing(Client(), prefs, feed))
    feed.generated_at = "b"
    assert list(briefing_cache.cached_briefing(Client(), prefs, feed)) == first
    assert len(calls) == 1
    prefs.favorite_teams = ["A"]
    list(briefing_cache.cached_briefing(Client(), prefs, feed))
    item.home_team = "C"
    list(briefing_cache.cached_briefing(Client(), prefs, feed))
    assert len(calls) == 3


def test_template_never_contacts_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(briefing_cache, "connect", lambda: connect(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(briefing_cache.config, "settings", lambda: {})
    feed = PersonalizedFeedResponse(items=[], generated_at="x", risk_profile="moderate",
                                    total_matches=0, favorite_matches_count=0)
    out = list(briefing_cache.cached_briefing(object(), UserPreferences(), feed))
    assert out[-1].data == {"iterations": 0, "success": True}


def test_template_cache_invalidates_when_reference_coverage_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(briefing_cache, "connect", lambda: connect(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(briefing_cache.config, "settings", lambda: {})
    kickoff = datetime.now(timezone.utc).isoformat()
    item = FeedItem(match_id=1, home_team="A", away_team="B", league="PL", kickoff=kickoff,
                    is_favorite_team=False, is_favorite_league=False, value_bets_count=0, relevance_score=1)
    feed = PersonalizedFeedResponse(items=[item], generated_at="x", risk_profile="moderate",
                                    total_matches=1, favorite_matches_count=0)
    first = list(briefing_cache.cached_briefing(object(), UserPreferences(), feed))
    assert "0 de 1 con Pinnacle" in first[0].data["delta"]
    item._has_pinnacle = True
    second = list(briefing_cache.cached_briefing(object(), UserPreferences(), feed))
    assert "1 de 1 con Pinnacle" in second[0].data["delta"]
    assert first != second


def test_shared_semaphore_busy_and_released(monkeypatch):
    client = llm.OpenAICompatibleClient("http://unused", "model", queue_timeout=0)
    monkeypatch.setattr(client, "_stream_chat", lambda *_: iter([TextDelta("Hola")]))
    active = client.stream_chat([])
    assert next(active).text == "Hola"
    with pytest.raises(LLMBusy):
        list(client.stream_chat([]))
    active.close()
    assert list(client.stream_chat([])) == [TextDelta("Hola")]


def test_busy_emits_error_and_done():
    class Busy:
        def stream_chat(self, *_):
            raise LLMBusy("El asistente está atendiendo otra consulta")
    out = list(orchestrator.run_chat(Busy(), "hola", UserPreferences()))
    assert [e.event for e in out] == ["error", "done"]
    assert out[-1].data["success"] is False


def test_output_budget_sent_to_provider(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def iter_lines(self, **kwargs):
            yield 'data: ' + json.dumps({"choices": [{"delta": {"content": "hola"}}]})

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def post(url, **kwargs):
        captured.update(kwargs)
        return Response()
    monkeypatch.setattr(llm.requests, "post", post)
    list(llm.OpenAICompatibleClient("http://unused", "m", max_tokens=100).stream_chat([]))
    assert captured["json"]["max_tokens"] == 100
