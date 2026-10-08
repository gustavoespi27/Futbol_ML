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
    df = fd.parse(CSV)
    assert df.loc[0, "kickoff_utc"] == "2026-10-05T22:00:00Z"   # BST (UTC+1)
    assert df.loc[1, "kickoff_utc"] == "2026-01-15T20:00:00Z"   # GMT
    assert df.loc[0, "League"] == "Liga Profesional"


def test_store_is_idempotent_and_skips_incomplete_odds(conn):
    df = fd.parse(CSV)
    first = fd.store(conn, df)
    second = fd.store(conn, df)
    assert first["matches"] == 2 and second["odds"] == 0
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2
    # Fila 1: Max, Avg, BFE, B365 (sin Pinnacle) ; fila 2: Pinnacle, Max, Avg
    books = conn.execute("SELECT COUNT(DISTINCT bookmaker || match_id) FROM odds").fetchone()[0]
    assert books == 7
    assert conn.execute("SELECT MIN(is_closing) FROM odds").fetchone()[0] == 1
