"""Recolección diaria desde API-Football: calendario, cuotas pre-partido y detalles.

Uso:  python scripts/collect_daily.py
Pensado para ejecutarse 2 veces al día con el Programador de tareas de Windows
(ver scripts/register_task.ps1).
"""

import logging
import sys

from footy import config
from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest.api_football import ApiFootball
from footy.ingest.collect import run_daily


def main() -> int:
    log_dir = config.PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_dir / "collect_daily.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    conn = connect()
    repo.sync_competitions(conn)
    conn.commit()
    summary = run_daily(conn, ApiFootball(conn))
    logging.info("Resumen: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
