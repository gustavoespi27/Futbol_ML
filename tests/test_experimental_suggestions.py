"""Registro EXPERIMENTAL de sugerencias (tabla `suggestions`), sin uso en producción.

La cartera oficial (tabla `pro_bets`) se prueba en test_pro.py.
"""

import pytest

from footy.db import repository as repo
from footy.db.connection import connect
from footy.prediction import experimental_suggestions


def test_experimental_ledger_registers_once_and_settles_singles_and_doubles():
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
    assert experimental_suggestions.register(conn, [s1, s2], [double], "v")["suggestions"] == 4
    assert experimental_suggestions.register(conn, [s1, s2], [double], "v")["suggestions"] == 0       # no se duplica
    repo.upsert_match(conn, source="x", source_match_id="1", competition_id=comp, season="2026",
                      kickoff_utc="2026-10-10T20:00:00Z", home_team_id=h, away_team_id=a, status="finished",
                      home_goals=2, away_goals=1)
    rec = experimental_suggestions.record(conn)
    assert rec["settled"] == 1 and rec["pending"] == 2                                # la doble espera el 2º partido
    assert rec["won"] == 1 and rec["units"] == pytest.approx(1.0)
