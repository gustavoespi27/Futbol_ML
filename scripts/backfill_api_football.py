"""Carga el calendario/resultados de temporadas pasadas desde API-Football.

Uso:  python scripts/backfill_api_football.py CHL 2022 2023 2024
Solo descarga el calendario (1 petición por temporada). Los detalles de cada
partido (estadísticas, xG, alineaciones) quedan pendientes y los descarga
collect_daily.py con el presupuesto sobrante de cada día.
"""

import sys

from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest.api_football import ApiFootball
from footy.ingest.collect import backfill_season


def main(code: str, seasons: list[int]) -> int:
    conn = connect()
    repo.sync_competitions(conn)
    conn.commit()
    client = ApiFootball(conn)
    for season in seasons:
        n = backfill_season(client, conn, code, season)
        print(f"{code} {season}: {n} partidos")
    pending = conn.execute(
        "SELECT COUNT(*) FROM match_sources WHERE source = 'api_football' AND details_fetched_at IS NULL"
    ).fetchone()[0]
    print(f"Detalles pendientes (todas las ligas): {pending} | peticiones restantes hoy: {client.remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], [int(s) for s in sys.argv[2:]]))
