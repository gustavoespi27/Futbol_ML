import pytest

from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest.api_football import odds_rows, store_fixture, store_fixture_details


@pytest.fixture
def conn():
    c = connect(":memory:")
    repo.sync_competitions(c)
    return c


def fixture_item(status="FT", home_goals=2, away_goals=1):
    return {
        "fixture": {"id": 999, "date": "2026-10-10T19:00:00-03:00", "status": {"short": status},
                    "venue": {"name": "Estadio Monumental"}},
        "league": {"id": 265, "season": 2026, "round": "Regular Season - 20", "country": "Chile"},
        "teams": {"home": {"id": 1, "name": "Colo Colo"}, "away": {"id": 2, "name": "Universidad de Chile"}},
        "goals": {"home": home_goals, "away": away_goals},
        "score": {"fulltime": {"home": home_goals, "away": away_goals}},
    }


def test_store_fixture_converts_kickoff_to_utc(conn):
    mid = store_fixture(conn, fixture_item())
    row = conn.execute("SELECT kickoff_utc, status, home_goals FROM matches WHERE id = ?", (mid,)).fetchone()
    assert row["kickoff_utc"] == "2026-10-10T22:00:00Z"
    assert row["status"] == "finished" and row["home_goals"] == 2


def test_scheduled_fixture_has_no_goals(conn):
    mid = store_fixture(conn, fixture_item(status="NS", home_goals=None, away_goals=None))
    row = conn.execute("SELECT status, home_goals FROM matches WHERE id = ?", (mid,)).fetchone()
    assert row["status"] == "scheduled" and row["home_goals"] is None


def test_untracked_league_is_ignored(conn):
    item = fixture_item()
    item["league"]["id"] = 99999                   # liga que no está en settings.yaml
    assert store_fixture(conn, item) is None


def test_store_fixture_details(conn):
    item = fixture_item()
    item["statistics"] = [
        {"team": {"id": 1}, "statistics": [{"type": "Ball Possession", "value": "55%"},
                                            {"type": "expected_goals", "value": "1.34"}]},
        {"team": {"id": 2}, "statistics": [{"type": "Ball Possession", "value": "45%"}]},
    ]
    item["lineups"] = [{"team": {"id": 1}, "formation": "4-3-3",
                        "startXI": [{"player": {"id": 10, "name": "A", "pos": "F", "grid": "4:1"}}],
                        "substitutes": [{"player": {"id": 11, "name": "B", "pos": "M", "grid": None}}]}]
    item["players"] = [{"team": {"id": 1}, "players": [
        {"player": {"id": 10, "name": "A"},
         "statistics": [{"games": {"minutes": 90, "rating": "7.1", "substitute": False}, "goals": {"total": 1}}]}]}]
    store_fixture_details(conn, item)

    stats = dict(conn.execute("SELECT stat, value FROM team_match_stats WHERE value > 50").fetchall())
    assert stats == {"ball_possession": 55.0}
    assert conn.execute("SELECT value FROM team_match_stats WHERE stat = 'expected_goals'").fetchone()[0] == 1.34
    assert conn.execute("SELECT COUNT(*), SUM(is_starter) FROM lineups").fetchone()[:] == (2, 1)
    pstats = dict(conn.execute("SELECT stat, value FROM player_match_stats").fetchall())
    assert pstats["games_minutes"] == 90 and pstats["games_rating"] == 7.1 and pstats["goals_total"] == 1
    assert conn.execute("SELECT details_fetched_at FROM match_sources").fetchone()[0] is not None


def test_odds_rows_parses_markets():
    item = {"bookmakers": [{"name": "Pinnacle", "bets": [
        {"id": 1, "name": "Match Winner", "values": [{"value": "Home", "odd": "2.10"},
                                                      {"value": "Draw", "odd": "3.30"},
                                                      {"value": "Away", "odd": "3.60"}]},
        {"id": 5, "name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": "2.05"},
                                                          {"value": "Under 2.5", "odd": "1.80"}]},
        {"id": 8, "name": "Both Teams Score", "values": [{"value": "Yes", "odd": "1.95"}]},
        {"id": 10, "name": "Exact Score", "values": [{"value": "1:0", "odd": "7.0"}]},
    ]}]}
    rows = odds_rows(1, item, "2026-10-09T12:00:00Z")
    got = {(r["market"], r["line"], r["selection"]): r["price"] for r in rows}
    assert got == {("1X2", 0.0, "H"): 2.10, ("1X2", 0.0, "D"): 3.30, ("1X2", 0.0, "A"): 3.60,
                   ("OU", 2.5, "OVER"): 2.05, ("OU", 2.5, "UNDER"): 1.80, ("BTTS", 0.0, "YES"): 1.95}


def test_international_backfill_creates_national_teams_once(conn):
    from footy.ingest.collect import backfill_pending

    class FakeClient:
        calls = 0

        def get(self, endpoint, **params):
            FakeClient.calls += 1
            item = fixture_item()
            item["league"] = {"id": params["league"], "season": params["season"], "round": "Group A"}
            item["teams"] = {"home": {"id": 26, "name": "Argentina"}, "away": {"id": 2383, "name": "Chile"}}
            return {"response": [item]}

    done = backfill_pending(FakeClient(), conn, limit=2)
    assert len(done) == 2 and FakeClient.calls == 2                   # respeta el límite por ejecución
    country = conn.execute("SELECT DISTINCT t.country FROM teams t JOIN matches m ON t.id = m.home_team_id "
                           "JOIN competitions c ON c.id = m.competition_id WHERE c.type = 'international'").fetchall()
    assert [r[0] for r in country] == ["World"]                        # selecciones separadas de los clubes
    backfill_pending(FakeClient(), conn, limit=2)
    assert FakeClient.calls == 4                                       # las ya cargadas no se repiten


def test_domestic_cup_links_league_teams_and_creates_new_ones_in_country(conn):
    comp = repo.competition_id(conn, "SP1")
    madrid = repo.resolve_team(conn, "football_data", "Real Madrid", "Real Madrid", "Spain")
    betis = repo.resolve_team(conn, "football_data", "Betis", "Betis", "Spain")
    repo.upsert_match(conn, source="football_data", source_match_id="1", competition_id=comp, season="2026",
                      kickoff_utc=repo.utc_now()[:10] + "T00:00:00Z", home_team_id=madrid, away_team_id=betis,
                      status="finished", home_goals=1, away_goals=0)
    item = fixture_item(status="NS", home_goals=None, away_goals=None)
    item["league"] = {"id": 143, "season": 2026, "round": "1st Round", "country": "Spain"}          # Copa del Rey
    item["teams"] = {"home": {"id": 9001, "name": "Cultural Leonesa"}, "away": {"id": 541, "name": "Real Madrid CF"}}
    mid = store_fixture(conn, item)
    row = conn.execute("SELECT home_team_id, away_team_id FROM matches WHERE id = ?", (mid,)).fetchone()
    assert row["away_team_id"] == madrid                               # mismo equipo que en la liga, no un duplicado
    home = conn.execute("SELECT country FROM teams WHERE id = ?", (row["home_team_id"],)).fetchone()
    assert home["country"] == "Spain"                                  # equipo nuevo con su país, no 'unknown'


def test_history_only_cups_are_not_offered_in_the_league_search():
    from footy.web.services.catalog import league_catalog

    codes = {r["code"] for r in league_catalog([])}
    assert {"E1", "JPN", "USA"} <= codes and not {"CDR", "FACUP", "COPA_CHL"} & codes
