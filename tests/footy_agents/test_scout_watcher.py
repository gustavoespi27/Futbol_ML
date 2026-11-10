"""Integración: precio ESPN ofrecido, referencia intacta y aviso existente del Vigía."""

import numpy as np
import pytest
import test_odds_scout_cycle as cycle
from test_odds_comparison import add
from test_odds_scout_parser import fixture

from footy.betting import pro
from footy.db.repository import insert_odds
from footy.prediction.tracking import latest_market_odds
from footy.web.services import betting, context
from footy_agents import watcher
from footy_agents.odds_scout import parse_event_odds


@pytest.fixture
def db(tmp_path):
    yield from cycle.db.__wrapped__(tmp_path)


def snapshot(db):
    odds = latest_market_odds(db, 1)["1X2"]
    return {
        "ref": "m:1",
        "home": "Armenia",
        "away": "Cyprus",
        "home_id": 1,
        "away_id": 2,
        "league": "UNL",
        "league_name": "Nations League",
        "kickoff": "2026-11-12T17:00:00Z",
        "p_official": [0.5, 0.3, 0.2],
        "odds_1x2": {b: [p[s] for s in "HDA"] for b, p in odds.items()},
        "pro": pro.evaluate(odds),
    }


def test_espn_ingestion_reaches_existing_value_bet_notice(db):
    add(db, "Pinnacle", [2, 3.5, 4])
    before = snapshot(db)
    watcher.run(db, [before], cycle.NOW, suggestions=betting.current_suggestions([before]))
    rows = [{**r, "match_id": 1} for r in parse_event_odds(fixture("close"), cycle.NOW)]
    insert_odds(db, rows)
    db.commit()
    after = snapshot(db)
    assert any(p["book"] == "DraftKings" and p["bet"] for p in after["pro"])
    assert watcher.perceive([after])[1]["value"]
    result = watcher.run(db, [after], cycle.NOW, suggestions=betting.current_suggestions([after]))
    notices = db.execute("SELECT text FROM agent_alerts WHERE kind='value_bet'").fetchall()
    assert len(notices) == 1 and "DraftKings" in notices[0][0] and "Pinnacle" in notices[0][0]
    assert any(d.kind == "value_bet" and d.selected for d in result.decisions)
    watcher.run(db, [after], cycle.NOW, suggestions=betting.current_suggestions([after]))
    assert db.execute("SELECT COUNT(*) FROM agent_alerts WHERE kind='value_bet'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM pro_bets").fetchone()[0] == 0


@pytest.mark.parametrize("provider", ["DraftKings", "Otro proveedor ESPN"])
def test_espn_never_becomes_probability_reference(monkeypatch, provider):
    monkeypatch.setattr(context, "load_params", lambda: {})
    monkeypatch.setattr(context, "league_names", lambda: {"TEST": "Prueba"})
    monkeypatch.setattr(context, "_international_prediction", lambda *a: None)
    prices = {
        "1X2": {provider: {"H": 2.25, "D": 3.2, "A": 3.1}},
        "OU": {provider: {(2.5, "OVER"): 2.1, (2.5, "UNDER"): 1.8}},
        "BTTS": {},
    }
    result = context._build_context(
        "f:test", "TEST", "A", "B", None, prices, cross_probs=np.array([0.5, 0.3, 0.2]), offered_only_books={provider}
    )
    assert result["market_book"] is None and result.get("p_market") is None
    assert result["p_official"] == pytest.approx([0.5, 0.3, 0.2], abs=0.001)
    assert result["pro"] == []
    if provider == "DraftKings":
        assert provider in result["odds_1x2"]


def test_espn_provider_cannot_impersonate_sharp():
    event = fixture("close")
    event["competitions"][0]["odds"][0]["provider"]["name"] = "Pinnacle"
    reasons = []
    assert parse_event_odds(event, cycle.NOW, reasons) == []
    assert any("referencia Pinnacle" in reason for reason in reasons)
