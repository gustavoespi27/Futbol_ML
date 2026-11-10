"""Comparador directo de SQLite: ninguna referencia distinta de Pinnacle y sin cuotas futuras."""

from datetime import timedelta

import pytest
import test_odds_scout_cycle as cycle
from test_odds_scout_cycle import NOW

from footy.db.repository import insert_odds
from footy_agents.grounding import verify_numbers
from footy_agents.odds_comparison import compare
from footy_agents.schemas import ToolCallRecord


@pytest.fixture
def db(tmp_path):
    yield from cycle.db.__wrapped__(tmp_path)


def add(conn, book, prices, stamp="2026-11-09T00:00:00Z"):
    insert_odds(
        conn,
        [
            {
                "match_id": 1,
                "source": "test",
                "bookmaker": book,
                "market": "1X2",
                "line": 0,
                "selection": s,
                "price": p,
                "captured_at": stamp,
                "is_closing": 0,
            }
            for s, p in zip("HDA", prices)
        ],
    )
    conn.commit()


def test_no_odds(db):
    data = compare(db, 1, NOW)
    assert data["status"] == "no_odds" and not data["selections"]
    assert "Ninguna casa publica cuotas todavía" in data["note"]
    assert data["comparison_text"] == data["note"]
    assert "precios ofrecidos" not in data["comparison_text"]
    with pytest.raises(ValueError):
        compare(db, 999, NOW)


def test_offered_price_without_sharp_is_never_value(db):
    add(db, "DraftKings", [2.5, 3.2, 3.1])
    data = compare(db, 1, NOW)
    assert data["status"] == "no_pinnacle"
    assert all(s["edge"] is None and s["pinnacle_fair_odds"] is None for s in data["selections"])
    assert "Sin Pinnacle" in data["comparison_text"]


def test_best_prices_and_pinnacle_fair_only(db):
    add(db, "Pinnacle", [2.0, 3.5, 4.0])
    add(db, "DraftKings", [2.3, 3.3, 3.8])
    add(db, "Bet365", [2.1, 3.6, 3.7])
    add(db, "Market Max", [9.0, 9.0, 9.0])
    data = compare(db, 1, NOW)
    assert data["status"] == "ok"
    assert [s["bookmaker"] for s in data["selections"]] == ["DraftKings", "Bet365", "DraftKings"]
    expected = (1 / 2) / (1 / 2 + 1 / 3.5 + 1 / 4)
    assert data["selections"][0]["edge"] == pytest.approx(2.3 * expected - 1)
    assert data["overround"]["Pinnacle"] == pytest.approx(1 / 2 + 1 / 3.5 + 1 / 4 - 1, abs=1e-6)
    rec = ToolCallRecord(tool_name="request_odds", arguments={}, result=data, success=True, execution_time_ms=0)
    assert verify_numbers(data["comparison_text"], [rec]).verified


def test_future_and_postkickoff_prices_are_excluded(db):
    add(db, "DraftKings", [2.5, 3.2, 3.1], "2026-11-13T00:00:00Z")
    assert compare(db, 1, NOW + timedelta(days=4))["status"] == "no_odds"
    add(db, "Pinnacle", [2, 3.5, 4], "2026-11-11T00:00:00Z")
    assert compare(db, 1, NOW)["status"] == "no_odds"
