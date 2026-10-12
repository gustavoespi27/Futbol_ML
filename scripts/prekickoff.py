"""Cuota fresca y pronóstico final de los partidos que empiezan en las próximas horas.

Lo ejecuta el Programador de tareas cada 30 minutos (scripts/register_task.ps1). Cada partido de una liga con
`collect_odds` recibe una cuota más en sus últimas `prekickoff_hours` (la más cercana al cierre, que es la más
precisa) y se registra el pronóstico final con ella, siempre antes del inicio. Sin partidos que lo necesiten no
consulta la API (ni siquiera /status).
"""

import logging
import sys
from datetime import datetime, timedelta, timezone

from footy import config
from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest.api_football import ApiFootball, ApiUnavailable, BudgetExhausted
from footy.ingest.collect import collect_odds
from footy.prediction import tracking

log = logging.getLogger("prekickoff")


def pending(conn, hours: float) -> int:
    """Partidos que empiezan dentro de `hours` sin una cuota de API-Football de las últimas `hours`."""
    comps = config.settings()["competitions"]
    codes = [c for c, v in comps.items() if v.get("collect_odds")]
    now = datetime.now(timezone.utc)
    return conn.execute(
        f"""SELECT COUNT(*) FROM matches m JOIN competitions c ON c.id = m.competition_id
            JOIN match_sources s ON s.match_id = m.id AND s.source = 'api_football'
            WHERE c.code IN ({",".join("?" * len(codes))}) AND m.status = 'scheduled'
              AND m.kickoff_utc BETWEEN ? AND ?
              AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.match_id = m.id AND o.source = 'api_football'
                              AND o.captured_at > ?)""",
        (*codes, repo.to_iso(now), repo.to_iso(now + timedelta(hours=hours)),
         repo.to_iso(now - timedelta(hours=hours)))).fetchone()[0]


def main() -> int:
    log_dir = config.PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(log_dir / "prekickoff.log", encoding="utf-8")])
    hours = config.settings()["api_football"].get("prekickoff_hours", 2)
    conn = connect()
    n = pending(conn, hours)
    if not n:
        return 0
    try:
        client = ApiFootball(conn)
        matches, rows = collect_odds(client, conn, horizon_hours=hours, refresh_hours=hours)
    except (BudgetExhausted, ApiUnavailable) as e:
        log.warning("Sin cuotas pre-partido: %s", e)
        return 0
    log.info("Pendientes %s · cuotas %s partidos (%s filas) · quedan %s peticiones · pronósticos finales %s",
             n, matches, rows, client.remaining, tracking.register_scheduled(conn, horizon_hours=hours))
    return 0


if __name__ == "__main__":
    sys.exit(main())
