"""ESPN sin red: eventos con la forma del endpoint público (scoreboard) y vinculación con la base."""

import pytest

from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest import espn


@pytest.fixture
def conn():
    c = connect(":memory:")
    repo.sync_competitions(c)
    return c


def team(tid, name, short=None):
    return {"id": str(tid), "displayName": name, "shortDisplayName": short or name, "name": name, "location": name}


def event(eid, home, away, date="2026-10-17T14:00Z", state="pre", name="STATUS_SCHEDULED", score=("0", "0"),
          clock="0'", completed=False, linescores=None):
    sides = []
    for side, t, s in (("home", home, score[0]), ("away", away, score[1])):
        c = {"homeAway": side, "team": t, "score": s}
        if linescores:
            c["linescores"] = [{"value": v} for v in linescores[side]]
        sides.append(c)
    return {"id": str(eid), "date": date, "season": {"year": 2026},
            "status": {"displayClock": clock, "type": {"name": name, "state": state, "completed": completed,
                                                       "shortDetail": "HT" if name == "STATUS_HALFTIME" else ""}},
            "competitions": [{"competitors": sides}]}


def league_match(conn, code, home, away, kickoff, country):
    h = repo.resolve_team(conn, "football_data", home, home, country)
    a = repo.resolve_team(conn, "football_data", away, away, country)
    return repo.upsert_match(conn, source="football_data", source_match_id=f"{home}-{away}", season="2026/2027",
                             competition_id=repo.competition_id(conn, code), kickoff_utc=kickoff, home_team_id=h,
                             away_team_id=a, status="scheduled"), h, a


def test_status_mapping():
    st = lambda name, state, done=False: {"type": {"name": name, "state": state, "completed": done}}  # noqa: E731
    assert espn.map_status(st("STATUS_SCHEDULED", "pre")) == "scheduled"
    assert espn.map_status(st("STATUS_SECOND_HALF", "in")) == "live"
    assert espn.map_status(st("STATUS_FULL_TIME", "post", True)) == "finished"
    assert espn.map_status(st("STATUS_POSTPONED", "post")) == "postponed"
    assert espn.map_status(st("STATUS_ABANDONED", "post")) == "cancelled"


def test_extra_time_keeps_the_90_minute_score():
    ev = event(1, team(1, "A"), team(2, "B"), state="post", name="STATUS_FINAL_AET", score=("2", "1"),
               completed=True, linescores={"home": [1, 0, 1], "away": [0, 1, 0]})
    assert espn.final_goals(ev) == (1, 1)


def test_event_links_to_the_match_another_source_already_has(conn):
    mid, man_utd, spurs = league_match(conn, "E0", "Man United", "Tottenham", "2026-10-17T14:00:00Z", "England")
    ev = event(401, team(360, "Manchester United", "Man United"), team(367, "Tottenham Hotspur", "Spurs"))
    assert espn.store_event(conn, "E0", ev) == mid                     # mismo partido, no uno nuevo
    later = event(402, team(360, "Manchester United"), team(367, "Tottenham Hotspur"), date="2026-10-24T14:00Z")
    new = espn.store_event(conn, "E0", later)                          # partido futuro: equipos ya conocidos por id
    row = conn.execute("SELECT home_team_id, away_team_id FROM matches WHERE id = ?", (new,)).fetchone()
    assert (row["home_team_id"], row["away_team_id"]) == (man_utd, spurs)


def test_future_match_links_teams_by_name_variants(conn):
    _, tucuman, _ = league_match(conn, "ARG", "Atl. Tucuman", "Gimnasia L.P.", "2026-09-01T20:00:00Z", "Argentina")
    league_match(conn, "ARG", "Gimnasia Mendoza", "Estudiantes Rio Cuarto", "2026-09-02T20:00:00Z", "Argentina")
    ev = event(500, team(9785, "Atlético Tucumán", "Atl Tucumán"), team(9, "Gimnasia La Plata", "Gimnasia LP"),
               date="2026-10-20T20:00Z")
    row = conn.execute("SELECT th.name AS h, ta.name AS a FROM matches m JOIN teams th ON th.id = m.home_team_id "
                       "JOIN teams ta ON ta.id = m.away_team_id WHERE m.id = ?",
                       (espn.store_event(conn, "ARG", ev),)).fetchone()
    assert (row["h"], row["a"]) == ("Atl. Tucuman", "Gimnasia L.P.")   # no Gimnasia Mendoza, no equipos nuevos
    assert conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 4 and tucuman


def test_european_cup_does_not_link_by_short_name_to_another_club(conn):
    league_match(conn, "F2", "Red Star", "Annecy", "2026-09-01T18:00:00Z", "France")
    league_match(conn, "P1", "Sp Braga", "Porto", "2026-09-01T20:00:00Z", "Portugal")
    ev = event(700, team(2290, "Red Star Belgrade", "Red Star"), team(2994, "Braga"), date="2026-10-22T19:00Z")
    row = conn.execute("SELECT th.name AS h, th.country AS hc, ta.name AS a FROM matches m "
                       "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
                       "WHERE m.id = ?", (espn.store_event(conn, "UECL", ev),)).fetchone()
    assert (row["h"], row["hc"]) == ("Red Star Belgrade", "unknown")   # club nuevo, no el Red Star francés
    assert row["a"] == "Sp Braga"                                       # mismas palabras clave: mismo club


def test_live_score_is_kept_apart_and_finished_match_never_goes_back(conn):
    mid, _, _ = league_match(conn, "E0", "Arsenal", "Chelsea", "2026-10-17T14:00:00Z", "England")
    home, away = team(359, "Arsenal"), team(363, "Chelsea")
    espn.store_event(conn, "E0", event(9, home, away, state="in", name="STATUS_SECOND_HALF", score=("1", "0"),
                                       clock="67'"))
    live = conn.execute("SELECT home_goals, away_goals, clock FROM live_scores WHERE match_id = ?", (mid,)).fetchone()
    assert tuple(live) == (1, 0, "67'")
    st = conn.execute("SELECT status, home_goals FROM matches WHERE id = ?", (mid,)).fetchone()
    assert st["status"] == "live" and st["home_goals"] is None          # el parcial no se mezcla con el resultado
    espn.store_event(conn, "E0", event(9, home, away, state="post", name="STATUS_FULL_TIME", score=("2", "0"),
                                       completed=True))
    assert conn.execute("SELECT COUNT(*) FROM live_scores").fetchone()[0] == 0
    repo.upsert_match(conn, source="football_data", source_match_id="Arsenal-Chelsea", season="2026/2027",
                      competition_id=repo.competition_id(conn, "E0"), kickoff_utc="2026-10-17T14:00:00Z",
                      home_team_id=1, away_team_id=2, status="scheduled")             # fuente atrasada
    st = conn.execute("SELECT status, home_goals, away_goals FROM matches WHERE id = ?", (mid,)).fetchone()
    assert tuple(st) == ("finished", 2, 0)


def test_competitions_sync_leagues_before_cups():
    order = list(espn.slugs())
    assert order.index("DNK") < order.index("UECL") < order.index("WC")


def test_team_with_an_espn_id_is_never_linked_to_another_espn_id(conn):
    league_match(conn, "ARG", "River Plate", "Boca Juniors", "2026-09-01T20:00:00Z", "Argentina")
    espn.store_event(conn, "ARG", event(1, team(16, "River Plate"), team(5, "Boca Juniors"),
                                        date="2026-09-01T20:00Z"))
    ev = event(2, team(5498, "River Plate"), team(77, "Bolívar"), date="2026-04-10T00:30Z")     # el de Uruguay
    row = conn.execute("SELECT th.country FROM matches m JOIN teams th ON th.id = m.home_team_id WHERE m.id = ?",
                       (espn.store_event(conn, "LIB", ev),)).fetchone()
    assert row["country"] == "unknown"                                   # club nuevo, no el River Plate argentino
