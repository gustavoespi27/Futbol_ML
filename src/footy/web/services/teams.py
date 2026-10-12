"""Ficha de un club: liga principal, posición en la tabla, Elo, forma reciente, próximos partidos y promedios de la
temporada. Todo con partidos ya terminados (o programados, para el calendario): nada posterior a ahora."""

import sqlite3
from datetime import timedelta

from footy.db import repository as repo
from footy.leagues import load_params
from footy.web.services import standings as _standings
from footy.web.services.catalog import COUNTRY_ES, league_names
from footy.web.services.common import _f
from footy.web.services.context import predictor, recent_form

PROFILE_RECENT = 8
PROFILE_UPCOMING = 3
SEASON_FALLBACK_DAYS = 365          # copas sin tabla: promedios del último año


def _main_league(conn: sqlite3.Connection, team_id: int, now: str) -> str | None:
    """Liga de su partido más reciente ya jugado (o, si aún no juega ninguna, de su próximo partido de liga)."""
    row = conn.execute(
        """SELECT c.code FROM matches m JOIN competitions c ON c.id = m.competition_id
           WHERE c.type = 'league' AND ? IN (m.home_team_id, m.away_team_id)
           ORDER BY m.kickoff_utc > ?, CASE WHEN m.kickoff_utc > ? THEN m.kickoff_utc END,
                    m.kickoff_utc DESC LIMIT 1""", (team_id, now, now)).fetchone()
    return row["code"] if row else None


def _upcoming(conn: sqlite3.Connection, team_id: int, now: str, names: dict) -> list[dict]:
    rows = conn.execute(
        """SELECT m.id, m.kickoff_utc, m.home_team_id = :t AS is_home, c.code,
                  CASE WHEN m.home_team_id = :t THEN m.away_team_id ELSE m.home_team_id END AS opp, o.name
           FROM matches m JOIN competitions c ON c.id = m.competition_id
           JOIN teams o ON o.id = CASE WHEN m.home_team_id = :t THEN m.away_team_id ELSE m.home_team_id END
           WHERE m.status = 'scheduled' AND m.kickoff_utc >= :now AND :t IN (m.home_team_id, m.away_team_id)
           ORDER BY m.kickoff_utc LIMIT :n""", {"t": team_id, "now": now, "n": PROFILE_UPCOMING}).fetchall()
    return [{"match_id": r["id"], "date": r["kickoff_utc"], "opponent": r["name"], "opponent_id": r["opp"],
             "is_home": bool(r["is_home"]), "league": r["code"], "league_name": names.get(r["code"], r["code"])}
            for r in rows]


def _season_stats(conn: sqlite3.Connection, team_id: int, league: str | None, now: str) -> dict | None:
    """Goles y tiros al arco por partido: en la temporada vigente de su liga (todas las competiciones desde su
    inicio) o, sin tabla, en el último año. Los tiros solo cuentan partidos que los tienen."""
    comp = conn.execute("SELECT id FROM competitions WHERE code = ?", (league,)).fetchone() if league else None
    window = _standings._window(conn, comp["id"], None) if comp else None
    since = window[1] if window else repo.to_iso(repo.from_iso(now) - timedelta(days=SEASON_FALLBACK_DAYS))
    r = conn.execute(
        """WITH g AS (
             SELECT id, home_goals AS gf, away_goals AS ga, away_team_id AS opp FROM matches
             WHERE home_team_id = :t AND status = 'finished' AND home_goals IS NOT NULL
               AND kickoff_utc >= :s AND kickoff_utc < :now
             UNION ALL
             SELECT id, away_goals, home_goals, home_team_id FROM matches
             WHERE away_team_id = :t AND status = 'finished' AND home_goals IS NOT NULL
               AND kickoff_utc >= :s AND kickoff_utc < :now),
           sot AS (
             SELECT g.id, MAX(CASE WHEN s.team_id = :t THEN s.value END) AS sf,
                    MAX(CASE WHEN s.team_id = g.opp THEN s.value END) AS sa
             FROM g JOIN team_match_stats s ON s.match_id = g.id AND s.stat = 'shots_on_goal'
             GROUP BY g.id)
           SELECT (SELECT COUNT(*) FROM g) AS n, (SELECT AVG(gf) FROM g) AS gf, (SELECT AVG(ga) FROM g) AS ga,
                  (SELECT AVG(sf) FROM sot) AS sf, (SELECT AVG(sa) FROM sot) AS sa,
                  (SELECT COUNT(sf) FROM sot) AS n_sot""", {"t": team_id, "s": since, "now": now}).fetchone()
    if not r["n"]:
        return None
    return {"since": since, "played": r["n"], "gf_pg": _f(r["gf"], 2), "ga_pg": _f(r["ga"], 2),
            "sot_pg": _f(r["sf"], 2), "sot_against_pg": _f(r["sa"], 2), "with_shots": r["n_sot"]}


def _elo(league: str | None, team_id: int) -> int | None:
    """Elo del equipo en el predictor de su liga (solo ligas con modelo; escala comparable dentro de la liga)."""
    if league not in load_params():
        return None
    ratings = predictor(league).ratings
    return round(float(ratings[team_id])) if team_id in ratings else None


def team_profile(conn: sqlite3.Connection, team_id: int) -> dict | None:
    """Respuesta de /api/teams/{id}. None si el equipo no existe."""
    team = conn.execute("SELECT id, name, country FROM teams WHERE id = ?", (team_id,)).fetchone()
    if team is None:
        return None
    now, names = repo.utc_now(), league_names()
    league = _main_league(conn, team_id, now)
    country = None if team["country"] in (None, "unknown") else COUNTRY_ES.get(team["country"], team["country"])
    out = {"id": team["id"], "name": team["name"], "country": country,
           "league": league, "league_name": league and names.get(league, league), "elo": _elo(league, team_id),
           "recent": recent_form(conn, [team_id], before_kickoff=now, n=PROFILE_RECENT).get(team_id, []),
           "upcoming": _upcoming(conn, team_id, now, names), "season": _season_stats(conn, team_id, league, now)}
    table = _standings.standings(conn, league) if league else None
    row = next((r for r in table["rows"] if r["team_id"] == team_id), None) if table else None
    if row:
        out["standing"] = {"pos": row["pos"], "teams": len(table["rows"]), "points": row["points"],
                           "played": row["played"], "won": row["won"], "drawn": row["drawn"], "lost": row["lost"],
                           "gf": row["gf"], "ga": row["ga"], "season": table["season"]}
    return out
