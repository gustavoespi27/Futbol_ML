import pytest

from footy.betting import suggestions as sg
from footy.db import repository as repo
from footy.db.connection import connect
from footy.prediction import suggested


def test_stake_is_fractional_kelly_with_cap():
    assert sg.stake_fraction(0.5, 2.2) == pytest.approx(0.25 * (0.5 * 2.2 - 1) / 1.2)
    assert sg.stake_fraction(0.4, 2.0) == 0                      # sin valor no se apuesta
    assert sg.stake_fraction(0.9, 2.0) == sg.MAX_STAKE           # tope
    assert sg.growth(0.4, 2.0) == 0
    assert sg.growth(0.55, 2.0) > 0


def test_pick_singles_applies_rule_and_one_per_match():
    cands = [
        {"match": 1, "key": "1", "p": 0.55, "odds": 2.0},                       # EV +10%: sí
        {"match": 1, "key": "O2.5", "p": 0.60, "odds": 1.75},                   # EV +5%: mismo partido, crece menos
        {"match": 2, "key": "2", "p": 0.20, "odds": 6.0},                       # cuota > 4 y p < 25%: no
        {"match": 3, "key": "X", "p": 0.30, "odds": 3.2},                       # EV -4%: no
        {"match": 4, "key": "1X", "p": 0.80, "odds": 1.40, "estimated": True},  # cuota estimada: no
        {"match": 5, "key": "U2.5", "p": 0.80, "odds": 1.25},                   # cuota < 1,30: no
    ]
    picks = sg.pick_singles(cands)
    assert [(p["match"], p["key"]) for p in picks] == [(1, "1")]
    assert picks[0]["risk"] == "medio" and picks[0]["ev"] == pytest.approx(0.10)


def test_pick_doubles_multiplies_and_uses_distinct_matches():
    singles = sg.pick_singles([{"match": i, "key": "1", "p": 0.55, "odds": 2.0} for i in range(3)])
    doubles = sg.pick_doubles(singles)
    assert len(doubles) == 3
    d = doubles[0]
    assert d["p"] == pytest.approx(0.55 ** 2) and d["odds"] == pytest.approx(4.0)
    assert d["legs"][0]["match"] != d["legs"][1]["match"]


def test_register_once_and_settle():
    conn = connect(":memory:")
    repo.sync_competitions(conn)
    comp = repo.competition_id(conn, "CHL")
    h = repo.resolve_team(conn, "x", "A", "A", "Chile")
    a = repo.resolve_team(conn, "x", "B", "B", "Chile")
    m1 = repo.upsert_match(conn, source="x", source_match_id="1", competition_id=comp, season="2026",
                           kickoff_utc="2026-10-10T20:00:00Z", home_team_id=h, away_team_id=a, status="scheduled")
    m2 = repo.upsert_match(conn, source="x", source_match_id="2", competition_id=comp, season="2026",
                           kickoff_utc="2026-10-17T20:00:00Z", home_team_id=a, away_team_id=h, status="scheduled")
    s1 = {"match": m1, "key": "1", "p": 0.55, "odds": 2.0, "book": "Bet365", "stake": 0.02}
    s2 = {"match": m2, "key": "O2.5", "p": 0.55, "odds": 2.0, "book": "Bet365", "stake": 0.02}
    double = {"legs": [s1, s2], "stake": 0.01}
    assert suggested.register(conn, [s1, s2], [double], "v")["suggestions"] == 4
    assert suggested.register(conn, [s1, s2], [double], "v")["suggestions"] == 0       # no se duplica
    repo.upsert_match(conn, source="x", source_match_id="1", competition_id=comp, season="2026",
                      kickoff_utc="2026-10-10T20:00:00Z", home_team_id=h, away_team_id=a, status="finished",
                      home_goals=2, away_goals=1)
    rec = suggested.record(conn)
    assert rec["settled"] == 1 and rec["pending"] == 2                                # la doble espera el 2º partido
    assert rec["won"] == 1 and rec["units"] == pytest.approx(1.0)
