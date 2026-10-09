import pytest

from footy.betting import pro
from footy.db import repository as repo
from footy.db.connection import connect
from footy.prediction import pro_ledger

PIN = {"H": 2.00, "D": 3.60, "A": 4.20}          # margen ~2,6%


def test_fair_requires_pinnacle_and_removes_margin():
    p = pro.fair_1x2({"Pinnacle": PIN})
    assert p.sum() == pytest.approx(1)
    assert p[0] < 1 / 2.00                                       # sin margen la probabilidad baja
    assert pro.fair_1x2({"Bet365": PIN}) is None                 # sin Pinnacle no hay precio justo


def test_line_shopping_and_rule():
    odds = {"Pinnacle": PIN, "Bet365": {"H": 2.05, "D": 3.5, "A": 4.0},
            "Betano": {"H": 2.25, "D": 3.4, "A": 4.6}, "Betfair": {"H": 9.0, "D": 9.0, "A": 9.0}}
    opps = {o["sel"]: o for o in pro.evaluate(odds)}
    assert opps["H"]["book"] == "Betano" and opps["H"]["odds"] == 2.25    # mejor cuota jugable (Betfair excluida)
    assert opps["H"]["bet"]                                               # 2,25 × p_justa - 1 >= 6%
    assert not opps["A"]["bet"] or opps["A"]["odds"] <= pro.MAX_ODDS
    assert opps["H"]["stake"] <= pro.MAX_STAKE


def test_pick_one_per_match_and_daily_cap():
    opp = {"key": "1", "sel": "H", "bet": True, "stake": pro.MAX_STAKE, "growth": 0.01}
    picks = pro.pick({i: [opp] for i in range(10)})
    assert sum(p["stake"] for p in picks) <= pro.MAX_DAILY + 1e-9
    assert len({p["match"] for p in picks}) == len(picks)


def test_ledger_places_once_settles_and_measures_clv():
    conn = connect(":memory:")
    repo.sync_competitions(conn)
    comp = repo.competition_id(conn, "CHL")
    h = repo.resolve_team(conn, "x", "A", "A", "Chile")
    a = repo.resolve_team(conn, "x", "B", "B", "Chile")
    mid = repo.upsert_match(conn, source="x", source_match_id="1", competition_id=comp, season="2026",
                            kickoff_utc="2099-01-01T20:00:00Z", home_team_id=h, away_team_id=a, status="scheduled")
    bet = {"match": mid, "sel": "H", "book": "Betano", "odds": 2.25, "p_fair": 0.48, "pinnacle": 2.0,
           "edge": 0.08, "stake": 0.02}
    assert pro_ledger.place(conn, [bet])["pro_bets"] == 1
    assert pro_ledger.place(conn, [bet])["pro_bets"] == 0                  # una vez por partido
    repo.insert_odds(conn, [dict(match_id=mid, source="api", bookmaker="Pinnacle", market="1X2", line=0.0,
                                 selection=s, price=p, captured_at="2099-01-01T19:00:00Z", is_closing=0)
                            for s, p in zip("HDA", (1.90, 3.7, 4.6))])
    repo.upsert_match(conn, source="x", source_match_id="1", competition_id=comp, season="2026",
                      kickoff_utc="2099-01-01T20:00:00Z", home_team_id=h, away_team_id=a, status="finished",
                      home_goals=1, away_goals=0)
    rec = pro_ledger.record(conn)
    assert rec["settled"] == 1 and rec["won"] == 1
    assert rec["bank"] == pytest.approx(100 * (1 + 0.02 * 1.25))
    item = rec["items"][0]
    assert item["clv"] == pytest.approx(2.25 * pro.fair_1x2({"Pinnacle": {"H": 1.9, "D": 3.7, "A": 4.6}})[0] - 1)
