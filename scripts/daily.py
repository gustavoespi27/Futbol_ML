"""Tarea diaria completa (la ejecuta el Programador de tareas, ver scripts/register_task.ps1).

1. ESPN: calendario (7 días), horarios, resultados y tiros. API-Football: cuotas pre-partido, más calendario y
   detalles de las ligas que ESPN no cubre.
2. football-data.co.uk: resultados y cuotas de cierre de la temporada en curso (todas las ligas).
3. Seguimiento: predicciones de los próximos partidos y apuestas sugeridas, registradas antes del kickoff.
4. Informe docs/seguimiento.md y, si el dashboard está abierto, refresco de sus cachés.

Cada paso es independiente: si uno falla, los demás se ejecutan igual (queda en logs/daily.log).
"""

import logging
import sys
from datetime import datetime, timedelta, timezone

import requests

from footy import config
from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest import football_data as fd
from footy.ingest.api_football import ApiFootball
from footy.ingest.collect import run_daily, run_espn
from footy.models import cross_league
from footy.prediction import ml_predict, recalibration, tracking
from footy.web import service

log = logging.getLogger("daily")


def update_current_season(conn) -> None:
    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 7 else now.year - 1
    since = repo.to_iso(now - timedelta(days=45))
    cfg = fd.leagues()
    for code in cfg["main"]:
        df = fd.download(code, seasons=[season])
        if not df.empty:
            log.info("%s: %s", code, fd.store(conn, df))
    for code in cfg["extra"]:
        df = fd.download(code)
        df = df[df.kickoff_utc >= since]     # el archivo trae todo el histórico; solo lo reciente cambia
        log.info("%s: %s", code, fd.store(conn, df))


def _save_cross(model) -> int:
    cross_league.save(model)
    return model.n_train


def main() -> int:
    log_dir = config.PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(log_dir / "daily.log", encoding="utf-8"),
                                  # con pythonw (tarea programada sin ventana) no hay consola: solo el archivo
                                  *([logging.StreamHandler(sys.stdout)] if sys.stdout else [])])
    conn = connect()
    repo.sync_competitions(conn)
    conn.commit()
    steps = [
        ("espn", lambda: log.info("ESPN: %s", run_espn(conn))),
        ("api_football", lambda: log.info("Resumen API: %s", run_daily(conn, ApiFootball(conn)))),
        ("football_data", lambda: update_current_season(conn)),
        ("recalibrate", lambda: log.info("Recalibración: %s", recalibration.update(conn))),
        ("cross_league", lambda: log.info("Modelo entre ligas: %s cruces de copas",
                                          _save_cross(cross_league.fit(conn)))),
        ("ml", lambda: log.info("ML: %s partidos", len(ml_predict.upcoming(refresh=True)))),
        ("tracking", lambda: log.info("Seguimiento: %s", tracking.register(conn, tracking.fetch_fixtures()))),
        ("tracking_api", lambda: log.info("Seguimiento API: %s", tracking.register_scheduled(conn))),
        ("tracking_cups", lambda: log.info("Seguimiento copas: %s", tracking.register_cross(conn))),
        ("suggestions", lambda: log.info("Sugerencias: %s", service.register_suggestions(conn))),
        ("reliable", lambda: log.info("Pronósticos fiables: %s", service.register_reliable(conn))),
        ("report", lambda: (config.PROJECT_ROOT / "docs" / "seguimiento.md").write_text(
            tracking.report(conn), encoding="utf-8", newline="\n")),
    ]
    failed = []
    for name, step in steps:
        try:
            step()
        except Exception:
            log.exception("Paso %s falló", name)
            conn.rollback()
            failed.append(name)
    try:
        requests.post("http://127.0.0.1:8000/api/refresh", timeout=3)
    except requests.RequestException:
        pass                                      # dashboard cerrado: no hay nada que refrescar
    log.info("Fin. Pasos con error: %s", failed or "ninguno")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
