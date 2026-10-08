"""Detecta equipos posiblemente duplicados entre fuentes y permite fusionarlos.

Uso:
  python scripts/check_teams.py                 # reporte
  python scripts/check_teams.py --merge 51 12   # fusiona el equipo 51 en el 12

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


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--merge", nargs=2, type=int, metavar=("FROM_ID", "INTO_ID"))
    args = p.parse_args()
    conn = connect()
    if args.merge:
        repo.merge_teams(conn, *args.merge)
        conn.commit()
        print(f"Equipo {args.merge[0]} fusionado en {args.merge[1]}")
    report(conn)


if __name__ == "__main__":
    main()
