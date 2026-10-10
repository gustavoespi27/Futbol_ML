import pytest

from footy.db import repository as repo
from footy.db.connection import connect


@pytest.fixture
def conn():
    c = connect(":memory:")
    repo.sync_competitions(c)
    return c


def test_normalize_name_strips_accents_and_punctuation():
    assert repo.normalize_name("Unión La Calera") == "union la calera"
    assert repo.normalize_name("Atletico-MG") == "atletico mg"


def test_resolve_team_links_sources_by_normalized_name(conn):
    a = repo.resolve_team(conn, "football_data", "Union La Calera", "Union La Calera", "Chile")
    b = repo.resolve_team(conn, "api_football", "1234", "Unión La Calera", "Chile")
    assert a == b
    # Mismo nombre en otro país es otro equipo
    c = repo.resolve_team(conn, "other", "x", "Union La Calera", "Peru")
    assert c != a


def test_merge_teams_repoints_references(conn):
    keep = repo.resolve_team(conn, "football_data", "Dep. Riestra", "Dep. Riestra", "Argentina")
    dup = repo.resolve_team(conn, "other", "476", "Riestra FC", "Argentina")
    assert keep != dup
    repo.merge_teams(conn, dup, keep)
    assert repo.resolve_team(conn, "other", "476", "Riestra FC", "Argentina") == keep
    assert conn.execute("SELECT COUNT(*) FROM teams WHERE id = ?", (dup,)).fetchone()[0] == 0


def test_resolve_team_is_stable_per_alias(conn):
    a = repo.resolve_team(conn, "api_football", "1", "Colo Colo", "Chile")
    assert repo.resolve_team(conn, "api_football", "1", "Colo-Colo renamed", "Chile") == a


def _match(conn, source, sid, kickoff, **kw):
    comp = repo.competition_id(conn, "CHL")
    h = repo.resolve_team(conn, source, "H", "Colo Colo", "Chile")
    a = repo.resolve_team(conn, source, "A", "Universidad de Chile", "Chile")
    return repo.upsert_match(conn, source=source, source_match_id=sid, competition_id=comp,
                             season="2026", kickoff_utc=kickoff, home_team_id=h, away_team_id=a,
                             status=kw.get("status", "scheduled"),
                             home_goals=kw.get("hg"), away_goals=kw.get("ag"))


def test_upsert_match_is_idempotent_and_updates_result(conn):
    m1 = _match(conn, "api_football", "10", "2026-10-10T22:00:00Z")
    m2 = _match(conn, "api_football", "10", "2026-10-10T22:00:00Z", status="finished", hg=2, ag=1)
    assert m1 == m2
    row = conn.execute("SELECT status, home_goals, away_goals FROM matches WHERE id = ?", (m1,)).fetchone()
    assert tuple(row) == ("finished", 2, 1)
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


def test_upsert_match_links_across_sources_with_time_offset(conn):
    m1 = _match(conn, "api_football", "10", "2026-10-10T22:00:00Z")
    m2 = _match(conn, "football_data", "2026-10-10|Colo Colo|U de Chile", "2026-10-10T23:00:00Z")
    assert m1 == m2
    # Un partido 2 meses después entre los mismos equipos es otro partido
    m3 = _match(conn, "football_data", "2026-12-10|x", "2026-12-10T23:00:00Z")
    assert m3 != m1


def test_insert_odds_ignores_duplicates(conn):
    m = _match(conn, "api_football", "10", "2026-10-10T22:00:00Z")
    row = dict(match_id=m, source="api_football", bookmaker="Pinnacle", market="1X2", line=0.0,
               selection="H", price=2.1, captured_at="2026-10-09T12:00:00Z", is_closing=0)
    assert repo.insert_odds(conn, [row]) == 1
    assert repo.insert_odds(conn, [row]) == 0


def test_normalize_name_handles_turkish_dotless_i():
    assert repo.normalize_name("Kasımpaşa") == "kasimpasa"


def test_fuzzy_team_match_within_competition(conn):
    comp = repo.competition_id(conn, "T1")
    names = ["Amedspor", "Erzurumspor", "Genclerbirligi", "Karagumruk", "Galatasaray", "Goztep"]
    ids = {n: repo.resolve_team(conn, "football_data", n, n, "Turkey") for n in names}
    for i, (h, a) in enumerate(zip(names, names[1:] + names[:1])):
        repo.upsert_match(conn, source="football_data", source_match_id=str(i), competition_id=comp, season="2026/2027",
                          kickoff_utc=f"2026-09-{10 + i:02d}T17:00:00Z", home_team_id=ids[h], away_team_id=ids[a],
                          status="finished", home_goals=1, away_goals=0)
    assert repo.fuzzy_team_match(conn, "Amed", "T1") == ids["Amedspor"]
    assert repo.fuzzy_team_match(conn, "Erzurumspor FK", "T1") == ids["Erzurumspor"]
    assert repo.fuzzy_team_match(conn, "Gençlerbirliği S.K.", "T1") == ids["Genclerbirligi"]
    assert repo.fuzzy_team_match(conn, "Fatih Karagümrük", "T1") == ids["Karagumruk"]
    assert repo.fuzzy_team_match(conn, "Göztepe", "T1") == ids["Goztep"]
    assert repo.fuzzy_team_match(conn, "Besiktas", "T1") is None          # sin candidato: no se inventa
    assert repo.fuzzy_team_match(conn, "Galatasaray", "I1") is None       # solo dentro de la competición


def test_connect_disk_uses_wal_and_initializes_schema_once(tmp_path, monkeypatch):
    from footy.db import connection

    db = tmp_path / "f.sqlite"
    c1 = connect(db)
    assert c1.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c1.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert c1.execute("SELECT 1 FROM sqlite_master WHERE name = 'matches'").fetchone()
    monkeypatch.setattr(connection, "_schema", lambda: (_ for _ in ()).throw(AssertionError("DDL repetido")))
    c2 = connect(db)                                           # misma base en el mismo proceso: no reaplica el DDL
    assert c2.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    c1.close()
    c2.close()


def test_connect_memory_always_gets_schema():
    for _ in range(2):
        c = connect(":memory:")
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name = 'matches'").fetchone()


def test_recent_form_returns_last_results_oldest_first(conn):
    from footy.web.services.context import recent_form

    comp = repo.competition_id(conn, "CHL")
    a = repo.resolve_team(conn, "x", "A", "A", "Chile")
    b = repo.resolve_team(conn, "x", "B", "B", "Chile")
    scores = [(2, 0), (1, 1), (0, 3), (1, 0), (2, 2), (0, 1)]            # resultados de A (local en los pares)
    for k, (hg, ag) in enumerate(scores):
        home, away = (a, b) if k % 2 == 0 else (b, a)
        g1, g2 = (hg, ag) if k % 2 == 0 else (ag, hg)
        repo.upsert_match(conn, source="x", source_match_id=str(k), competition_id=comp, season="2026",
                          kickoff_utc=f"2026-0{k + 1}-01T20:00:00Z", home_team_id=home, away_team_id=away,
                          status="finished", home_goals=g1, away_goals=g2)
    form = recent_form(conn, [a, b, None])
    assert form[a] == ["D", "L", "W", "D", "L"]                           # los 5 últimos, el más reciente al final
    assert form[b] == ["D", "W", "L", "D", "W"]
    assert recent_form(conn, []) == {}
