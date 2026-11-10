"""Parser probado sin red con un scoreboard ESPN recortado (2026-11-10)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from footy_agents.odds_scout import american_to_decimal, parse_event_odds

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def fixture(name):
    return json.loads(
        (Path(__file__).parents[1] / "fixtures" / "espn_odds" / f"{name}.json").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("raw,price", [("+125", 2.25), ("-135", 1.741), (220, 3.2)])
def test_conversion(raw, price):
    assert american_to_decimal(raw) == price


@pytest.mark.parametrize("raw", [None, True, 0, "nan", "inf", "mal"])
def test_bad_conversion(raw):
    with pytest.raises(ValueError):
        american_to_decimal(raw)


@pytest.mark.parametrize("name", ["close", "open"])
def test_fixture_prices(name):
    rows = parse_event_odds(fixture(name), NOW)
    assert len([r for r in rows if r["market"] == "1X2"]) == 3
    assert len([r for r in rows if r["market"] == "OU"]) == 2
    assert all(r["source"] == "espn_odds" and r["bookmaker"] == "DraftKings" and r["is_closing"] == 0 for r in rows)
    assert all(r["captured_at"] == "2026-11-10T00:00:00Z" for r in rows)
    assert next(r["price"] for r in rows if r["selection"] == "H") == (2.25 if name == "close" else 2.15)


@pytest.mark.parametrize("name", ["null", "no_draw"])
def test_missing_prices_are_not_invented(name):
    reasons = []
    assert not any(r["market"] == "1X2" for r in parse_event_odds(fixture(name), NOW, reasons))
    assert reasons


def test_bad_margin_and_started():
    event = fixture("close")
    for side in event["competitions"][0]["odds"][0]["moneyline"].values():
        side["close"] = {"odds": "+1000"}
    assert not any(r["market"] == "1X2" for r in parse_event_odds(event, NOW))
    assert parse_event_odds(event, datetime(2026, 11, 13, tzinfo=timezone.utc)) == []
