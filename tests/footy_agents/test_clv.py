"""Muestras sintéticas para intervalos y datos faltantes del CLV."""

import json
import sqlite3

import pandas as pd
import pytest

from footy_agents.analytics import clv
from footy_agents.analytics.clv import markdown, summarize


def test_reference_groups_missing_clv_and_cluster_bootstrap():
    bets = pd.DataFrame([
        {"match_id": 1, "market_reference": "Betfair", "clv": -0.1, "profit": -1},
        {"match_id": 2, "market_reference": "Betfair", "clv": -0.1, "profit": 1},
        {"match_id": 3, "market_reference": "Pinnacle", "clv": None, "profit": -1},
    ])
    rows = summarize(bets)
    assert rows[0]["clv"] == pytest.approx(-0.1)
    assert rows[0]["ic95"] == pytest.approx([-0.1, -0.1])
    assert rows[0]["yield"] == 0
    assert rows[1]["n_clv"] == 0 and rows[1]["ic95"] is None
    assert "insuficiente" in markdown(rows)
    assert summarize(pd.DataFrame()) == []


def test_attribution_preserves_duplicate_match_names_and_time(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE teams(id INTEGER, name TEXT);
        INSERT INTO teams VALUES(1,'A'),(2,'B');
        CREATE TABLE matches(id INTEGER, kickoff_utc TEXT, home_team_id INTEGER, away_team_id INTEGER,
                             status TEXT, home_goals INTEGER);
        INSERT INTO matches VALUES(1,'2026-01-02T12:00:00Z',1,2,'finished',1),
                                  (2,'2026-01-02T12:00:00Z',1,2,'finished',1);
        CREATE TABLE predictions(match_id INTEGER, model_version TEXT, created_at TEXT, extra_json TEXT);
    """)
    version = clv.tracking.ALL_VERSIONS[0]
    for match_id, reference in [(1, "Betfair"), (2, "Pinnacle")]:
        conn.execute("INSERT INTO predictions VALUES(?, ?, ?, ?)", (match_id, version, "2026-01-01T00:00:00Z",
                     json.dumps({"league": "E0", "market_reference": reference, "paper_bets": [{}]})))
    bets = pd.DataFrame([{"partido": "A vs B", "kickoff": "2026-01-02T12:00:00Z", "model_version": version}] * 2)
    monkeypatch.setattr(clv.tracking, "evaluate", lambda *args: (pd.DataFrame(), bets))
    out = clv.settled_bets(conn)
    assert out.match_id.tolist() == [1, 2]
    assert out.market_reference.tolist() == ["Betfair", "Pinnacle"]
    bets.loc[0, "partido"] = "Otro partido"
    with pytest.raises(ValueError, match="contrato"):
        clv.settled_bets(conn)
    conn.close()
