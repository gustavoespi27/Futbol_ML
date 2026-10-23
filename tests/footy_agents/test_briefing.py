"""Pruebas del resumen personalizado: ficha de hechos determinista, LLM simulado y respaldo con plantilla."""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

from footy_agents import briefing
from footy_agents.llm import LLMUnavailable, TextDelta
from footy_agents.schemas import FeedItem, PersonalizedFeedResponse, UserPreferences
from footy_agents.web import router

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def item(mid, kickoff, fav_team=False, fav_league=False, edge=None, home="A", away="B"):
    return FeedItem(match_id=mid, home_team=home, away_team=away, league="CHL", league_name="Primera Chile",
                    kickoff=kickoff, is_favorite_team=fav_team, is_favorite_league=fav_league,
                    value_bets_count=1 if edge else 0, best_edge=edge, relevance_score=0)


def feed(*items):
    return PersonalizedFeedResponse(items=list(items), generated_at="2026-10-23T12:00:00Z", risk_profile="moderate",
                                    total_matches=len(items), favorite_matches_count=0)


class FakeLLM:
    def __init__(self, turn):
        self.turn = turn
        self.messages = None

    def stream_chat(self, messages, tools=None):
        self.messages = messages
        assert tools is None                      # el resumen nunca ofrece herramientas
        if isinstance(self.turn, Exception):
            raise self.turn
        yield from self.turn


FEED = feed(
    item(1, "2026-10-23T23:00:00Z", fav_team=True, fav_league=True, home="Colo Colo", away="Everton"),
    item(2, "2026-10-23T18:00:00Z", edge=0.084, home="Boca", away="River"),
    item(3, "2026-10-23T20:00:00Z", fav_league=True, home="Palestino", away="Huachipato"),
    item(4, "2026-10-23T21:00:00Z"),                                   # no le interesa al usuario
    item(5, "2026-10-26T20:00:00Z", fav_team=True, home="Colo Colo", away="Cobresal"),  # fuera de 24 h
    item(6, "2026-10-23T10:00:00Z", fav_team=True),                    # ya empezó
)


def test_facts_selects_relevant_next_24h():
    f = briefing.facts(FEED, NOW)
    assert [r["partido"] for r in f["partidos_equipos_favoritos"]] == ["Colo Colo vs Everton"]
    assert f["partidos_equipos_favoritos"][0]["hora_chile"] == "20:00"          # 23:00 UTC = 20:00 en Chile (UTC-3)
    assert f["apuestas_con_valor"] == [{"partido": "Boca vs River", "liga": "Primera Chile", "hora_chile": "15:00",
                                        "equipo_favorito": False, "edge_pinnacle": "+8.4%"}]
    assert [r["partido"] for r in f["otros_partidos_ligas_favoritas"]] == ["Palestino vs Huachipato"]


def test_llm_writes_from_facts_only():
    client = FakeLLM([TextDelta("Hoy juega Colo Colo a las 20:00.")])
    out = list(briefing.run_briefing(client, UserPreferences(), FEED, NOW))
    assert [e.event for e in out] == ["token", "done"] and out[-1].data["success"] is True
    assert json.loads(client.messages[1]["content"]) == briefing.facts(FEED, NOW)
    assert "SOLO la ficha" in client.messages[0]["content"]


def test_template_when_llm_down():
    out = list(briefing.run_briefing(FakeLLM(LLMUnavailable("down")), UserPreferences(), FEED, NOW))
    text = out[0].data["delta"]
    assert "Colo Colo vs Everton (20:00)" in text and "Boca vs River (+8.4%)" in text
    assert out[-1].data == {"iterations": 1, "success": False}


def test_template_without_value_bets():
    text = briefing.template_briefing(briefing.facts(feed(), NOW))
    assert "no conviene apostar" in text


def test_briefing_endpoint(monkeypatch):
    def memory_db():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(router, "connect", memory_db)
    monkeypatch.setattr(router.service, "get_personalized_feed", lambda conn, user_id: feed())
    resp = router.briefing(user_id="default", client=FakeLLM([TextDelta("Nada relevante hoy.")]))

    async def collect():
        return [chunk async for chunk in resp.body_iterator]
    body = "".join(asyncio.run(collect()))
    assert body.startswith("event: token\n") and '"success": true' in body
