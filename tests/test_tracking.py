import json

import numpy as np
import pytest

from footy.db import repository as repo
from footy.db.connection import connect
from footy.prediction import tracking


@pytest.fixture
def conn():
    c = connect(":memory:")
    repo.sync_competitions(c)
    return c


def _match(conn, hg, ag):
    comp = repo.competition_id(conn, "T1")
    h = repo.resolve_team(conn, "football_data", "A", "A", "Turkey")
    a = repo.resolve_team(conn, "football_data", "B", "B", "Turkey")
    return repo.upsert_match(conn, source="x", source_match_id="1", competition_id=comp, season="2026/2027",
                             kickoff_utc="2026-10-10T17:00:00Z", home_team_id=h, away_team_id=a,
                             status="finished", home_goals=hg, away_goals=ag)


def _predict(conn, mid, created_at, paper_bets):
    extra = {"league": "T1", "p_final": [0.5, 0.3, 0.2], "paper_bets": paper_bets}
    conn.execute("""INSERT INTO predictions (match_id, model_version, created_at, p_home, p_draw, p_away, extra_json)
                    VALUES (?, ?, ?, 0.5, 0.3, 0.2, ?)""", (mid, tracking.MODEL_VERSION, created_at, json.dumps(extra)))


def test_evaluate_uses_last_pre_kickoff_prediction_and_computes_clv(conn):
    mid = _match(conn, 2, 0)
    bet = [{"book": "Bet365", "sel": "H", "odds": 2.2, "effective_odds": 2.2, "ev": 0.1}]
    _predict(conn, mid, "2026-10-09T10:00:00Z", [])
    _predict(conn, mid, "2026-10-10T10:00:00Z", bet)
    _predict(conn, mid, "2026-10-10T18:00:00Z", [])          # posterior al kickoff: se ignora
    repo.insert_odds(conn, [dict(match_id=mid, source="fd", bookmaker="Pinnacle", market="1X2", line=0.0,
                                 selection=s, price=p, captured_at="2026-10-10T17:00:00Z", is_closing=1)
                            for s, p in zip("HDA", (2.0, 3.5, 4.0))])
    matches, bets = tracking.evaluate(conn)
    assert len(matches) == 1 and len(bets) == 1
    fair_h = (1 / 2.0) / (1 / 2.0 + 1 / 3.5 + 1 / 4.0)
    assert bets.clv.iloc[0] == pytest.approx(2.2 * fair_h - 1)
    assert bets.profit.iloc[0] == pytest.approx(1.2)
    assert matches.ll_model.iloc[0] == pytest.approx(-np.log(0.5))
    assert "Ligas marcadas" in tracking.report(conn)


def test_odds_by_book_requires_complete_triplets():
    row = {"B365H": 2.0, "B365D": 3.4, "B365A": 3.9, "BFEH": 2.1, "BFED": None, "BFEA": 4.0}
    books = tracking._odds_by_book(row)
    assert list(books) == ["Bet365"]
