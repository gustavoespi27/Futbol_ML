"""Descarga y actualiza resultados + cuotas de cierre desde football-data.co.uk.

Uso:  python scripts/update_football_data.py [ARG BRA]
Idempotente: se puede ejecutar cuantas veces se quiera (football-data actualiza 1-2 veces por semana).
"""

import sys

from footy import config
from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest import football_data


def main(codes: list[str]) -> int:
    codes = codes or [c for c, v in config.settings()["competitions"].items() if "football_data_url" in v]
    conn = connect()
    repo.sync_competitions(conn)
    for code in codes:
        df = football_data.download(code)
        counts = football_data.store(conn, df)
        print(f"{code}: {len(df)} filas -> {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
