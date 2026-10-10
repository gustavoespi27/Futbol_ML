import numpy as np
import pandas as pd
import pytest

from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest import football_data as fd

CSV = """﻿Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,MaxCH,MaxCD,MaxCA,AvgCH,AvgCD,AvgCA,BFECH,BFECD,BFECA,B365CH,B365CD,B365CA
Argentina,Liga Profesional ,2026,05/10/2026,23:00,Velez Sarsfield,Platense,2,2,D,,,,1.95,3.2,5,1.89,3.11,4.45,2.02,3.3,4.8,1.81,3.1,5
Argentina,Liga Profesional,2026,15/01/2026,20:00,Platense,Velez Sarsfield,0,1,A,3.1,3.0,2.5,3.2,3.1,2.6,3.0,2.9,2.4,,,,,,
""".lstrip("﻿")


@pytest.fixture
def conn():
    c = connect(":memory:")
    repo.sync_competitions(c)
    return c


def test_parse_converts_uk_time_to_utc_with_dst():
    df = fd.parse_extra(CSV, "ARG")
    assert df.loc[0, "kickoff_utc"] == "2026-10-05T22:00:00Z"   # BST (UTC+1)
    assert df.loc[1, "kickoff_utc"] == "2026-01-15T20:00:00Z"   # GMT
    assert df.loc[0, "League"] == "Liga Profesional"


def test_store_is_idempotent_and_skips_incomplete_odds(conn):
    df = fd.parse_extra(CSV, "ARG")
    first = fd.store(conn, df)
    second = fd.store(conn, df)
    assert first["matches"] == 2 and second["odds"] == 0
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2
    # Fila 1: Max, Avg, BFE, B365 (sin Pinnacle) ; fila 2: Pinnacle, Max, Avg
    books = conn.execute("SELECT COUNT(DISTINCT bookmaker || match_id) FROM odds").fetchone()[0]
    assert books == 7
    assert conn.execute("SELECT MIN(is_closing) FROM odds").fetchone()[0] == 1


MAIN_CSV = """Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,HST,AST,PSCH,PSCD,PSCA
E1,17/08/12,Leeds,Wolves,1,0,H,12,8,5,2,2.5,3.3,2.9
"""


def test_parse_main_two_digit_year_and_default_time(conn):
    df = fd.parse_main(MAIN_CSV, "E1", "2012/2013")
    assert df.loc[0, "kickoff_utc"] == "2012-08-17T14:00:00Z"   # 15:00 BST asumido
    counts = fd.store(conn, df)
    assert counts == {"matches": 1, "odds": 3, "stats": 4, "skipped": 0}
    known = conn.execute("SELECT DISTINCT captured_at FROM team_match_stats").fetchone()[0]
    assert known == "2012-08-17T17:00:00Z"                       # stats: conocidas al terminar


def test_load_ou_closing_parametrized_in_chunks(conn, monkeypatch):
    from footy import data

    comp = repo.competition_id(conn, "ARG")
    h = repo.resolve_team(conn, "x", "A", "A", "Argentina")
    a = repo.resolve_team(conn, "x", "B", "B", "Argentina")
    mids = [repo.upsert_match(conn, source="x", source_match_id=str(k), competition_id=comp, season="2026",
                              kickoff_utc=f"2026-{3 * k + 1:02d}-01T20:00:00Z", home_team_id=h, away_team_id=a,
                              status="finished", home_goals=1, away_goals=1) for k in range(3)]
    rows = [{"match_id": m, "source": "x", "bookmaker": book, "market": "OU", "line": 2.5, "selection": sel,
             "price": price, "captured_at": "2026-01-01T00:00:00Z", "is_closing": 1}
            for m in mids[:2] for book, sel, price in (("Pinnacle", "OVER", 2.0), ("Pinnacle", "UNDER", 2.0),
                                                       ("Bet365", "OVER", 1.9), ("Bet365", "UNDER", 1.9))]
    repo.insert_odds(conn, rows)
    assert data.load_ou_closing(conn, []).empty                              # sin ids: sin consulta
    assert data.load_ou_closing(conn, [mids[2]]).empty                       # ids sin cuotas O/U
    merged = pd.DataFrame({"match_id": [mids[2]]}).merge(data.load_ou_closing(conn, [mids[2]]),
                                                          left_on="match_id", right_index=True, how="left")
    assert np.isnan(merged.p_over.to_numpy()).all()                         # sigue siendo numérico
    monkeypatch.setattr(data, "OU_CHUNK", 1)                                 # fuerza varios lotes
    out = data.load_ou_closing(conn, mids + [999999])
    assert sorted(out.index) == sorted(mids[:2])
    assert (out.dtypes == np.float64).all()                                   # lotes vacíos no cambian el tipo
    assert out["p_over"].tolist() == pytest.approx([0.5, 0.5])
    assert out["b365_over"].tolist() == pytest.approx([1.9, 1.9])
