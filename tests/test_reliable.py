import numpy as np
import pytest

from footy.db import repository as repo
from footy.db.connection import connect
from footy.prediction import recalibration, reliable


def test_temperature_shrinks_towards_one_with_little_data():
    rng = np.random.default_rng(0)
    truth = rng.dirichlet([3, 2, 3], 4000)
    y = np.array([rng.choice(3, p=p) for p in truth])
    over = recalibration.scale(truth, 0.7)                   # sistema demasiado seguro
    big = recalibration.fit(over, y)
    assert big["T_fit"] > 1.2 and big["T"] > 1.0             # detecta que debe suavizar
    assert big["ll_after"] < big["ll_before"]
    small = recalibration.fit(over[:40], y[:40])
    assert abs(small["T"] - 1) < abs(big["T"] - 1)           # con pocos datos el ajuste es menor
    assert recalibration.fit(over[:5], y[:5])["T"] == 1.0
    assert recalibration.scale([0.5, 0.3, 0.2], 1.0) == pytest.approx([0.5, 0.3, 0.2])


def _ctx(ref, options, kickoff="2099-01-01T20:00:00Z"):
    return {"ref": ref, "home": "A", "away": "B", "league": "CHL", "league_name": "Chile", "kickoff": kickoff,
            "source": "modelo + mercado", "options": options}


def test_candidates_pick_most_probable_simple_market_per_match():
    opt = lambda k, p: {"key": k, "label": k, "p": p, "odds": 1.4, "book": "Bet365"}  # noqa: E731
    ms = [_ctx("m:1", [opt("1", 0.72), opt("1X", 0.9), opt("O2.5", 0.66)]),           # doble oportunidad no cuenta
          _ctx("m:2", [opt("2", 0.55), opt("BTTS_N", 0.6)]),                          # nada llega al mínimo
          _ctx("m:3", [opt("U2.5", 0.81)]),
          _ctx("m:4", [opt("1", 0.95)], kickoff="2000-01-01T00:00:00Z")]              # ya jugado
    c = reliable.candidates(ms)
    assert [(x["match"], x["key"]) for x in c] == [(3, "U2.5"), (1, "1")]
    assert "81%" in c[0]["reason"] and "Bet365" in c[0]["reason"]


def test_register_once_and_settle():
    conn = connect(":memory:")
    repo.sync_competitions(conn)
    comp = repo.competition_id(conn, "CHL")
    h = repo.resolve_team(conn, "x", "A", "A", "Chile")
    a = repo.resolve_team(conn, "x", "B", "B", "Chile")
    kick = repo.utc_now()
    mid = repo.upsert_match(conn, source="x", source_match_id="1", competition_id=comp, season="2026",
                            kickoff_utc=kick, home_team_id=h, away_team_id=a, status="scheduled")
    pick = {"match": mid, "key": "1", "market": "1X2", "p": 0.7, "odds": 1.5, "book": "Bet365", "reason": "r",
            "kickoff": kick}
    assert reliable.register(conn, [pick])["daily_picks"] == 1
    assert reliable.register(conn, [pick])["daily_picks"] == 0
    repo.upsert_match(conn, source="x", source_match_id="1", competition_id=comp, season="2026",
                      kickoff_utc=kick, home_team_id=h, away_team_id=a, status="finished", home_goals=2, away_goals=0)
    rec = reliable.record(conn)
    assert rec["n"] == 1 and rec["hit"] == 1.0 and rec["expected"] == pytest.approx(0.7)
    assert rec["items"][0]["status"] == "acierto" and rec["yield_if_bet"] == pytest.approx(0.5)
