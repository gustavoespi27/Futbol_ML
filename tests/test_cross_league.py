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


def test_cross_league_simulator(monkeypatch):
    from footy.web.services import context, simulator

    conn = connect(":memory:")
    repo.sync_competitions(conn)
    eng = [repo.resolve_team(conn, "football_data", f"E{i}", f"E{i}", "England") for i in range(2)]
    gre = [repo.resolve_team(conn, "football_data", f"G{i}", f"G{i}", "Greece") for i in range(2)]
    for n, (code, h, a, hg, ag) in enumerate([("E0", eng[0], eng[1], 1, 1), ("G1", gre[0], gre[1], 1, 1),
                                               ("UCL", eng[0], gre[0], 3, 0), ("UCL", gre[1], eng[1], 0, 2)]):
        repo.upsert_match(conn, source="football_data", source_match_id=str(n), season="2024", status="finished",
                          competition_id=repo.competition_id(conn, code), kickoff_utc=f"2024-0{n + 1}-10T18:00:00Z",
                          home_team_id=h, away_team_id=a, home_goals=hg, away_goals=ag)
    model = cross_league.fit(conn)
    monkeypatch.setattr(cross_league, "load", lambda: model)
    monkeypatch.setattr(context, "connect", lambda: conn)
    monkeypatch.setattr(simulator, "connect", lambda: conn)
    r = simulator.predict_cross("E0", "G1", eng[1], gre[1], [2.0, 3.4, 4.0])
    assert r["source"] == "modelo entre ligas" and np.isclose(sum(r["p_official"]), 1, atol=1e-3)
    assert r["p_official"][0] > r["p_official"][2]                   # inglés de local contra griego
    assert r["recommendation"]["bet"] is False and len(r["betting"]["ev"]) == 3   # orientativo, nunca "apostar"
