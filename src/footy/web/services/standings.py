"""Tabla de posiciones de una liga, calculada con los partidos terminados de la base.

La temporada no se puede filtrar solo por la etiqueta `matches.season`: cada fuente la escribe distinto para la misma
campaña ("2026/2027" en football-data, "2026" en API-Football, "2027" para la J1 japonesa). Se toma la etiqueta del
último partido terminado de football-data (o de cualquier fuente si la liga no está ahí), la campaña empieza en su
primer partido y desde ahí cuentan todos los partidos terminados de la liga, tengan la etiqueta que tengan.

Es una tabla única: no separa zonas ni conferencias (Argentina, MLS) ni torneos cortos (Apertura/Clausura).
"""

import sqlite3
import threading
import time
from datetime import timedelta

from footy.db import repository as repo
from footy.web.services.catalog import league_names

TTL = 300
_cache: dict[tuple, tuple[float, dict | None]] = {}
_lock = threading.Lock()


def _current_label(conn, comp_id: int) -> str | None:
    """Etiqueta de la campaña vigente: la del último resultado de football-data (no su calendario, que se pega a
    partidos que otra fuente creó con su propia etiqueta) o, si la liga no está ahí,
    la del último partido terminado de cualquier fuente."""
    row = conn.execute(
        """SELECT m.season FROM matches m
           WHERE m.competition_id = ? AND m.status = 'finished' AND m.home_goals IS NOT NULL
           ORDER BY EXISTS (SELECT 1 FROM match_sources s WHERE s.match_id = m.id
                            AND s.source = 'football_data') DESC, m.kickoff_utc DESC LIMIT 1""",
        (comp_id,)).fetchone()
    return row[0] if row else None


def _window(conn, comp_id: int, season: str | None) -> tuple[str, str, str] | None:
    """(etiqueta, inicio, fin) de la campaña pedida o de la vigente. La vigente llega hasta hoy: incluye los partidos
    que otras fuentes guardaron con otra etiqueta."""
    current = _current_label(conn, comp_id)
    season = season or current
    if season is None:
        return None
    start, last = conn.execute("SELECT MIN(kickoff_utc), MAX(kickoff_utc) FROM matches WHERE competition_id = ? "
                               "AND season = ?", (comp_id, season)).fetchone()
    if start is None:
        return None
    end = repo.utc_now() if season == current else repo.to_iso(repo.from_iso(last) + timedelta(days=1))
    return season, start, end


def league_standings(conn: sqlite3.Connection, league_code: str, season: str | None = None) -> list[dict]:
    """Tabla de la liga: pos, equipo, PJ, G, E, P, GF, GC, DG, puntos y últimos 5 resultados en la liga.
    Orden: puntos, diferencia de gol, goles a favor y nombre."""
    row = conn.execute("SELECT id, type FROM competitions WHERE code = ?", (league_code,)).fetchone()
    if row is None or row["type"] != "league":
        return []
    w = _window(conn, row["id"], season)
    if w is None:
        return []
    _, start, end = w
    games = """WITH g AS (
                 SELECT home_team_id AS team, home_goals AS gf, away_goals AS ga, kickoff_utc FROM matches
                 WHERE competition_id = :c AND status = 'finished' AND home_goals IS NOT NULL
                   AND kickoff_utc >= :s AND kickoff_utc <= :e
                 UNION ALL
                 SELECT away_team_id, away_goals, home_goals, kickoff_utc FROM matches
                 WHERE competition_id = :c AND status = 'finished' AND home_goals IS NOT NULL
                   AND kickoff_utc >= :s AND kickoff_utc <= :e)"""
    params = {"c": row["id"], "s": start, "e": end}
    rows = conn.execute(
        games + """
        SELECT g.team AS team_id, t.name, COUNT(*) AS played, SUM(gf > ga) AS won, SUM(gf = ga) AS drawn,
               SUM(gf < ga) AS lost, SUM(gf) AS gf, SUM(ga) AS ga, SUM(gf) - SUM(ga) AS gd,
               3 * SUM(gf > ga) + SUM(gf = ga) AS points
        FROM g JOIN teams t ON t.id = g.team GROUP BY g.team
        ORDER BY points DESC, gd DESC, gf DESC, t.name ASC""", params).fetchall()
    recent: dict[int, list[str]] = {}
    for team, gf, ga in conn.execute(
            games + """
            SELECT team, gf, ga FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY team ORDER BY kickoff_utc DESC) AS rn
                                      FROM g) WHERE rn <= 5 ORDER BY team, kickoff_utc""", params):
        recent.setdefault(team, []).append("W" if gf > ga else "D" if gf == ga else "L")
    return [{"pos": i, **dict(r), "recent": recent.get(r["team_id"], [])} for i, r in enumerate(rows, 1)]


def standings(conn: sqlite3.Connection, league_code: str, season: str | None = None) -> dict | None:
    """Respuesta de /api/standings (cacheada TTL segundos). None si no es una liga o no hay partidos."""
    key = (league_code, season)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    row = conn.execute("SELECT id FROM competitions WHERE code = ?", (league_code,)).fetchone()
    w = _window(conn, row["id"], season) if row else None
    rows = league_standings(conn, league_code, season) if w else []
    out = None if not rows else {"league": league_code, "league_name": league_names().get(league_code, league_code),
                                 "season": w[0], "since": w[1], "rows": rows}
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def summary(conn: sqlite3.Connection, league_code: str, home_id: int | None, away_id: int | None) -> dict | None:
    """Posición y puntos de ambos equipos en la tabla vigente (para el resumen del partido)."""
    data = standings(conn, league_code)
    if not data:
        return None
    by_team = {r["team_id"]: r for r in data["rows"]}
    h, a = by_team.get(home_id), by_team.get(away_id)
    if h is None and a is None:
        return None
    return {"home_pos": h and h["pos"], "home_pts": h and h["points"],
            "away_pos": a and a["pos"], "away_pts": a and a["points"]}


def clear_cache() -> None:
    with _lock:
        _cache.clear()
