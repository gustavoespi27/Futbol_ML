"""Detecta equipos posiblemente duplicados entre fuentes y permite fusionarlos.

Uso:
  python scripts/check_teams.py                 # reporte
  python scripts/check_teams.py --merge 51 12   # fusiona el equipo 51 en el 12 (y los partidos que quedan dobles)

Sospechosos: equipos creados SOLO por api_football en un país donde existe
histórico de football_data. Los equipos históricos que API-Football no ha visto
(descendidos hace años) son normales y no se reportan.
"""

import argparse
import difflib

from footy.db import repository as repo
from footy.db.connection import connect


def report(conn) -> None:
    rows = conn.execute(
        """SELECT t.id, t.name, t.country, GROUP_CONCAT(DISTINCT a.source) AS sources
           FROM teams t JOIN team_aliases a ON a.team_id = t.id
           GROUP BY t.id ORDER BY t.country, t.name"""
    ).fetchall()
    by_country: dict[str, list] = {}
    for r in rows:
        by_country.setdefault(r["country"], []).append(r)

    found = False
    for country, teams in by_country.items():
        sources = {s for t in teams for s in t["sources"].split(",")}
        if "football_data" not in sources:
            continue
        for t in teams:
            if t["sources"] != "api_football":
                continue
            others = [o for o in teams if "football_data" in o["sources"]]
            names = {o["name"]: o["id"] for o in others}
            sug = difflib.get_close_matches(t["name"], list(names), n=3, cutoff=0.4)
            found = True
            print(f"[{country}] {t['id']:>5} {t['name']!r} (solo {t['sources']}) -> "
                  + ", ".join(f"{s!r}={names[s]}" for s in sug))
    if not found:
        print("Sin equipos sospechosos.")


def merge_duplicate_matches(conn, team_id: int) -> int:
    """Después de fusionar equipos, el mismo partido puede quedar dos veces (una por cada fuente que usaba un equipo
    distinto). Se queda el que tiene resultado y más fuentes."""
    pairs = conn.execute(
        """SELECT a.id, b.id FROM matches a JOIN matches b
           ON a.competition_id = b.competition_id AND a.home_team_id = b.home_team_id
              AND a.away_team_id = b.away_team_id AND a.id < b.id
              AND ABS(julianday(a.kickoff_utc) - julianday(b.kickoff_utc)) < 1.5
           WHERE ? IN (a.home_team_id, a.away_team_id)""", (team_id,)).fetchall()
    score = lambda mid: conn.execute(  # noqa: E731
        """SELECT (status = 'finished'), (SELECT COUNT(*) FROM match_sources WHERE match_id = ?) FROM matches
           WHERE id = ?""", (mid, mid)).fetchone()
    for a, b in pairs:
        keep, drop = (a, b) if tuple(score(a)) >= tuple(score(b)) else (b, a)
        repo.merge_matches(conn, drop, keep)
        print(f"Partido {drop} fusionado en {keep}")
    return len(pairs)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--merge", nargs=2, type=int, metavar=("FROM_ID", "INTO_ID"))
    args = p.parse_args()
    conn = connect()
    if args.merge:
        repo.merge_teams(conn, *args.merge)
        merge_duplicate_matches(conn, args.merge[1])
        conn.commit()
        print(f"Equipo {args.merge[0]} fusionado en {args.merge[1]}")
    report(conn)


if __name__ == "__main__":
    main()
