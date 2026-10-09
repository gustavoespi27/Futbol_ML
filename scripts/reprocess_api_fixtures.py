"""Vuelve a guardar los fixtures de las respuestas crudas de API-Football (data/raw/api_football/*/),
sin gastar peticiones. Útil al agregar una competición a config/settings.yaml.

Uso:  python scripts/reprocess_api_fixtures.py
"""

import json
import sys

from footy import config
from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest.api_football import SOURCE, competitions_by_api_id, store_fixture


def main() -> int:
    conn = connect()
    repo.sync_competitions(conn)
    tracked = competitions_by_api_id()
    n = 0
    for f in sorted((config.path("raw") / SOURCE).glob("*/*_fixtures_*.json")):
        for item in json.loads(f.read_text(encoding="utf-8")).get("response", []):
            if item.get("league", {}).get("id") in tracked and store_fixture(conn, item):
                n += 1
        conn.commit()
    print(f"{n} fixtures guardados/actualizados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
