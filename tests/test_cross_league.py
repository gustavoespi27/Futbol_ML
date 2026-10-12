"""Modelo entre ligas: el ajuste por liga sale de los cruces de copas."""

import numpy as np

from footy.db import repository as repo
from footy.db.connection import connect
from footy.models import cross_league


def test_league_offset_learned_from_cup_matches():
    conn = connect(":memory:")
    repo.sync_competitions(conn)
    strong = [repo.resolve_team(conn, "football_data", f"E{i}", f"E{i}", "England") for i in range(4)]
    weak = [repo.resolve_team(conn, "football_data", f"G{i}", f"G{i}", "Greece") for i in range(4)]
    n = 0

    def play(code, h, a, hg, ag, day):
        nonlocal n
        n += 1
        repo.upsert_match(conn, source="football_data", source_match_id=str(n), season="2024",
                          competition_id=repo.competition_id(conn, code), status="finished", home_goals=hg,
                          away_goals=ag, kickoff_utc=f"2024-{1 + day // 28:02d}-{1 + day % 28:02d}T18:00:00Z",
                          home_team_id=h, away_team_id=a)

    day = 0
    for _ in range(3):                      # ligas equilibradas por dentro: mismo Elo en las dos
        for teams, code in ((strong, "E0"), (weak, "G1")):
            for i in range(4):
                for j in range(4):
                    if i != j:
                        play(code, teams[i], teams[j], 1, 1, day)
            day += 1
    for k in range(40):                     # en las copas, los ingleses ganan casi siempre
        h, a = (strong[k % 4], weak[(k + 1) % 4]) if k % 2 else (weak[k % 4], strong[(k + 1) % 4])
        play("UCL", h, a, *((2, 0) if h in strong else (0, 2)) if k % 10 else (1, 1), day + k)
    model = cross_league.fit(conn)
    assert model.offsets["E0"] > model.offsets["G1"]
    p = model.probabilities(strong[0], weak[0])
    assert p[0] > p[2] and np.isclose(p.sum(), 1)
    assert model.probabilities(weak[0], strong[0])[2] > model.probabilities(weak[0], strong[0])[0]
