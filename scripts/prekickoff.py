"""Cuota fresca y pronóstico final de los partidos que empiezan en las próximas horas.

Lo ejecuta el Programador de tareas cada 30 minutos (scripts/register_task.ps1). Cada partido de una liga con
`collect_odds` recibe una cuota más en sus últimas `prekickoff_hours` (la más cercana al cierre, que es la más
precisa) y se registra el pronóstico final con ella, siempre antes del inicio. Sin partidos que lo necesiten no
consulta la API (ni siquiera /status).
"""

import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from footy import config
from footy.db.connection import connect
from footy_agents import automation

log = logging.getLogger("prekickoff")


def pending(conn: sqlite3.Connection, hours: float) -> int:
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
        (*codes, now.strftime("%Y-%m-%dT%H:%M:%SZ"),
         (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchone()[0]


def starts_within(conn: sqlite3.Connection, hours: float) -> bool:
    now = datetime.now(timezone.utc)
    return bool(conn.execute("SELECT 1 FROM matches WHERE status='scheduled' AND kickoff_utc BETWEEN ? AND ? LIMIT 1",
                             (now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchone())


def main() -> int:
    log_dir = config.PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(log_dir / "prekickoff.log", encoding="utf-8")])
    hours = config.settings()["api_football"].get("prekickoff_hours", 2)
    conn = connect()
    try:
        # Antes de importar pandas/modelos o muestrear CPU durante cinco segundos.
        if not starts_within(conn, 12) or not pending(conn, hours):
            log.info("Sin partidos pendientes en las próximas 12 h: salida ligera")
            automation.record_step("prekickoff", "cuotas", "omitido: sin pendientes")
            return 0
        return automation.run_task("prekickoff", lambda: work(conn, hours), urgent=lambda: starts_within(conn, 1.5))
    finally:
        conn.close()
        try:
            from footy_agents.odds_scout import run_safely as scout_safely
            scout_safely()
        except (ImportError, sqlite3.Error, ValueError, KeyError):
            log.exception("No se pudo ejecutar el Ojeador")
        try:
            from footy_agents.watcher import run_safely
            run_safely()
        except Exception:  # noqa: BLE001 - ni un fallo al importar el vigía rompe el pipeline
            log.exception("No se pudo ejecutar el vigía")


def work(conn: sqlite3.Connection, hours: float) -> int:
    from footy.ingest.api_football import ApiFootball, ApiUnavailable, BudgetExhausted
    from footy.ingest.collect import collect_odds
    from footy.prediction import tracking
    from footy.web import service
    from footy.web.services import snapshots

    try:
        client = ApiFootball(conn)
        matches, rows = collect_odds(client, conn, horizon_hours=hours, refresh_hours=hours)
    except (BudgetExhausted, ApiUnavailable) as exc:
        log.warning("Sin cuotas pre-partido: %s", exc)
        return 0
    predictions = tracking.register_scheduled(conn, horizon_hours=hours)
    log.info("Cuotas %s partidos (%s filas) · quedan %s peticiones · pronósticos finales %s",
             matches, rows, client.remaining, predictions)
    automation.record_step("prekickoff", "cuotas y predicciones", "ejecutado")
    if rows or predictions.get("predictions", 0):
        snapshots.advance_revision()
        log.info("Precalculado web: %s partidos", len(service.upcoming(refresh=True)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
