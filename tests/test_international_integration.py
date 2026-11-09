"""Referencia Pinnacle emparejada y protección contra registros prospectivos de selecciones."""

from datetime import datetime, timezone

import numpy as np
import pytest
from scripts.eval_international import paired_pinnacle
from test_international import database, insert_match, match

from footy.betting.devig import proportional
from footy.ingest import international as source
from footy.models import international
from footy.prediction import pro_ledger, reliable
from footy.web.services import betting, context


@pytest.fixture
def fitted():
    return international.fit([match(day=1 + i * 3, hg=i % 4, ag=(i + 1) % 3) for i in range(36)], source.TeamNames())


def test_pinnacle_uses_last_complete_snapshot_and_excludes_later_odds(fitted):
    conn = database()
    insert_match(conn, 1, "2022-01-05T18:00:00Z")

    def odds(captured, prices, bookmaker="Pinnacle"):
        conn.executemany("INSERT INTO odds (match_id,source,bookmaker,market,line,selection,price,"
                         "captured_at,is_closing) "
                         "VALUES (1,'test',?,'1X2',0,?,?,?,0)",
                         [(bookmaker, s, p, captured) for s, p in zip("HDA", prices)])

    odds("2022-01-04T18:00:00Z", [2, 3, 4])
    odds("2022-01-05T17:00:00Z", [1.2])  # snapshot incompleto, no mezclar fechas
    odds("2022-01-05T19:00:00Z", [1.1, 8, 12])  # posterior al kickoff, no usar
    odds("2022-01-05T17:30:00Z", [1.1, 8, 12], "Betfair")  # no sustituir Pinnacle
    result = paired_pinnacle(conn, fitted, [])
    assert result["model"]["n"] == result["pinnacle"]["n"] == 1
    assert result["rows"][0]["captured_at"] == "2022-01-04T18:00:00Z"
    assert np.allclose(result["rows"][0]["pinnacle"], proportional(np.array([[2, 3, 4]]))[0])
    conn.execute("DELETE FROM odds WHERE bookmaker='Pinnacle'")
    assert paired_pinnacle(conn, fitted, [])["pinnacle"]["n"] == 0


def build_context(monkeypatch, fitted, books=None, home="France"):
    monkeypatch.setattr(international, "load", lambda: fitted)
    monkeypatch.setattr(context, "load_params", lambda: {})
    monkeypatch.setattr(context, "league_names", lambda: {"UNL": "Nations League"})
    return context._build_context("s:UNL", "UNL", home, "Brazil", "2026-11-12T18:00:00Z",
                                   {"1X2": books or {}, "OU": {}, "BTTS": {}})


def test_without_pinnacle_official_probability_is_international_model(monkeypatch, fitted):
    result = build_context(monkeypatch, fitted, {"Bet365": {"H": 9, "D": 3, "A": 1.2}})
    expected = fitted.predict("France", "Brazil", datetime(2026, 11, 12, 18, tzinfo=timezone.utc), False)[0]
    assert result["source"] == "modelo selecciones" and result["market_book"] is None
    assert np.allclose(result["p_official"], expected, atol=.0001)
    assert not result["has_sharp"]
    assert not any(option["verdict"]["level"] == "green" for option in result["options"])


def test_with_pinnacle_market_has_priority_and_model_remains_visible(monkeypatch, fitted):
    result = build_context(monkeypatch, fitted, {"Pinnacle": {"H": 2, "D": 3, "A": 4},
                                               "Bet365": {"H": 9, "D": 3, "A": 1.2}})
    assert result["source"] == "mercado" and result["market_book"] == "Pinnacle"
    assert np.allclose(result["p_official"], proportional(np.array([[2, 3, 4]]))[0], atol=.0001)
    assert result["p_model"] and "selecciones" in result["model_name"]


def test_no_artifact_or_excluded_team_does_not_invent_probability(monkeypatch, fitted):
    assert build_context(monkeypatch, None)["source"] == "sin datos"
    assert build_context(monkeypatch, fitted, home="France U23")["source"] == "sin datos"


def test_international_never_enters_paper_ledger_or_prospective_picks(monkeypatch):
    matches = [{"league": "UNL", "source": "mercado"}, {"league": "FRIENDLY", "source": "modelo selecciones"},
               {"league": "E0", "source": "modelo"}]
    seen = []

    def suggestions(rows):
        seen.append([row["league"] for row in rows])
        return {"singles": []}

    def candidates(rows):
        seen.append([row["league"] for row in rows])
        return []

    monkeypatch.setattr(betting, "current_suggestions", suggestions)
    monkeypatch.setattr(pro_ledger, "place", lambda conn, singles: {"pro_bets": len(singles)})
    monkeypatch.setattr(reliable, "candidates", candidates)
    monkeypatch.setattr(reliable, "register", lambda conn, picks: {"daily_picks": len(picks)})
    assert betting.register_suggestions(matches, conn=object()) == {"pro_bets": 0}
    assert betting.register_reliable(matches, conn=object()) == {"daily_picks": 0}
    assert seen == [["E0"], ["E0"]]
