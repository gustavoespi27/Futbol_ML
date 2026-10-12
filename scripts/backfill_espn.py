"""Carga historial de competiciones desde ESPN (sin cuota), mes a mes.

Uso:
  python scripts/backfill_espn.py                       # copas de clubes desde 2022-08 (por defecto)
  python scripts/backfill_espn.py UCL LIB --from 2023-01

Sirve sobre todo para las copas internacionales de clubes: son los únicos cruces entre ligas de distintos países y
con ellos se estima la fuerza relativa de cada liga (modelo entre ligas). Ligas primero, después copas: para cargar
una copa conviene que la tarea diaria ya haya sincronizado las ligas (así cada club tiene su id de ESPN).
"""

import argparse
import logging
from datetime import date

from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest import espn

CLUB_CUPS = ["UCL", "UEL", "UECL", "LIB", "SUD"]


def months(start: str, end: date) -> list[str]:
    y, m = map(int, start.split("-"))
    out = []
    while (y, m) <= (end.year, end.month):
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", default=CLUB_CUPS)
    ap.add_argument("--from", dest="start", default="2022-08")
    args = ap.parse_args()
    conn = connect()
    repo.sync_competitions(conn)
    client = espn.Espn()
    for code in args.codes:
        print(code, espn.backfill_months(conn, client, code, months(args.start, date.today())), "partidos")


if __name__ == "__main__":
    main()
