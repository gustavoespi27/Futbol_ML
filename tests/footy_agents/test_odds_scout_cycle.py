"""Ciclo del Ojeador sin red: agrupación, presupuesto, transacciones y deduplicación."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from test_odds_scout_parser import fixture

from footy.db.connection import connect
from footy_agents import odds_scout as scout
from footy_agents.scout_schemas import ScoutPerception

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "scout.sqlite")
    conn.execute("INSERT INTO competitions(id,code,name,type) VALUES(1,'UNL','Nations League','international')")
    conn.execute("INSERT INTO teams(id,name) VALUES(1,'Armenia'),(2,'Cyprus')")
    for id_ in (1, 2):
        conn.execute(
            "INSERT INTO matches(id,competition_id,season,kickoff_utc,home_team_id,away_team_id,status,"
            "created_at,updated_at) VALUES(?,1,'2026','2026-11-12T17:00:00Z',1,2,'scheduled',"
            "'2026-11-01T00:00:00Z','2026-11-01T00:00:00Z')",
            (id_,),
        )
        conn.execute(
            "INSERT INTO match_sources(source,source_match_id,match_id) VALUES('espn',?,?)",
            ("401861146" if id_ == 1 else "other", id_),
        )
    conn.commit()
    yield conn
    conn.close()


def test_grouped_budget_and_real_ids(db):
    event = fixture("close")
    client = Mock()
    client.scoreboard.return_value = [event]
    result = scout.run(db, NOW, budget=1, client=client)
    assert result.actions == 1 and result.inserted == 5
    assert client.scoreboard.call_count == 1
    assert all(r[0] == 1 for r in db.execute("SELECT match_id FROM odds"))
    assert any("id ESPN exacto" in d.reason for d in result.decisions)
    assert any(d.source == "api_football" and not d.selected for d in result.decisions)
    assert len(db.execute("SELECT * FROM agent_scout_log").fetchall()) == 1
    assert scout.run(db, NOW, budget=1, client=client).inserted == 0
    assert db.execute("SELECT COUNT(*) FROM odds").fetchone()[0] == 5


def test_no_network_when_recent(db):
    client = Mock()
    client.scoreboard.return_value = [fixture("close")]
    scout.run(db, NOW, matches=scout.upcoming(db, NOW)[:1], client=client)
    client.reset_mock()
    result = scout.run(db, NOW + timedelta(minutes=30), matches=scout.upcoming(db, NOW)[:1], client=client)
    assert result.actions == 0
    client.scoreboard.assert_not_called()


def test_dry_run_never_initializes_or_writes(db):
    before = list(db.iterdump())
    assert scout.run(db, NOW, dry_run=True).actions == 0
    assert list(db.iterdump()) == before


def test_budget_priority_and_ttl():
    base = ScoutPerception(
        match_id=1,
        home="A",
        away="B",
        league="UNL",
        kickoff="2026-11-12T00:00:00Z",
        hours_to_kickoff=3,
        favorite=False,
        has_odds=False,
        has_pinnacle=False,
        slug="unl",
        event_id="a",
        espn_date="20261111",
    )
    other = base.model_copy(update={"match_id": 2, "slug": "other", "hours_to_kickoff": 4})
    decisions = scout.plan([other, base], 1, NOW)
    assert [d.match_id for d in decisions if d.selected] == [1]
    fresh = base.model_copy(update={"last_capture": "2026-11-09T22:00:00Z"})
    assert any(d.selected for d in scout.plan([fresh], 1, NOW))
    fresh.hours_to_kickoff = 10
    assert not any(d.selected for d in scout.plan([fresh], 1, NOW))
    assert not any(d.selected for d in scout.plan([base.model_copy(update={"event_id": None})], 1, NOW))
    with pytest.raises(ValueError):
        scout.plan([base], 41, NOW)


def test_init_does_not_commit_outer_transaction(db):
    db.execute("INSERT INTO teams(id,name) VALUES(3,'Preservar')")
    scout.init_tables(db)
    assert db.in_transaction
    db.rollback()
    assert not db.execute("SELECT 1 FROM teams WHERE id=3").fetchone()


def test_fetch_after_kickoff_discarded(db):
    from footy.ingest.espn import EspnUnavailable

    perception = scout.perceive(db, scout.upcoming(db, NOW), NOW)
    decisions = scout.plan(perception, 1, NOW)
    client = Mock()
    client.scoreboard.return_value = [fixture("close")]
    actions, inserted = scout.act(db, perception, decisions, client, lambda: NOW + timedelta(days=4))
    assert actions == 1 and inserted == 0
    client.scoreboard.side_effect = EspnUnavailable("sin red")
    actions, inserted = scout.act(db, perception, decisions, client, lambda: NOW)
    assert actions == 1 and inserted == 0
    assert any("no disponible" in d.reason for d in decisions)
