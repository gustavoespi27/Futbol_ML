"""Tareas de recolección con API-Football, ordenadas por urgencia.

1. Cuotas pre-partido: irrecuperables si no se capturan a tiempo.
2. Calendario/resultados por fecha: la ventana gratuita es ayer..mañana.
3. Detalles por partido (estadísticas, alineaciones, jugadores): recuperables
   en cualquier momento con /fixtures?id=, así que usan el presupuesto sobrante.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from footy import config
from footy.db import repository as repo
from footy.ingest.api_football import (
    SOURCE,
    ApiError,
    ApiFootball,
    BudgetExhausted,
    competitions_by_api_id,
    odds_rows,
    store_fixture,
    store_fixture_details,
)

log = logging.getLogger(__name__)


def collect_fixtures_by_date(client: ApiFootball, conn: sqlite3.Connection, dates: list[str]) -> int:
    tracked = competitions_by_api_id()
    n = 0
    for d in dates:
        try:
            items = client.get("fixtures", date=d)["response"]
        except ApiError as e:
            log.warning("fixtures %s: %s", d, e)
            continue
        for item in items:
            if item["league"]["id"] in tracked and store_fixture(conn, item):
                n += 1
        conn.commit()
    return n


def collect_odds(client: ApiFootball, conn: sqlite3.Connection, horizon_hours: float,
                 refresh_hours: float | None = None) -> tuple[int, int]:
    """Un snapshot de cuotas por partido próximo de las ligas con collect_odds. Devuelve (partidos, filas).
    Los partidos con snapshot de hace menos de `refresh_hours` se saltan (presupuesto de 100 peticiones/día)."""
    comps = config.settings()["competitions"]
    codes = [c for c, v in comps.items() if v.get("collect_odds")]
    refresh_hours = refresh_hours or config.settings()["api_football"].get("odds_refresh_hours", 10)
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        f"""SELECT m.id, ms.source_match_id, c.code FROM matches m
            JOIN competitions c ON c.id = m.competition_id
            JOIN match_sources ms ON ms.match_id = m.id AND ms.source = ?
            WHERE c.code IN ({",".join("?" * len(codes))})
              AND m.status = 'scheduled' AND m.kickoff_utc BETWEEN ? AND ?
              AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.match_id = m.id AND o.source = ? AND o.captured_at > ?)
            ORDER BY m.kickoff_utc""",
        (SOURCE, *codes, repo.to_iso(now), repo.to_iso(now + timedelta(hours=horizon_hours)),
         SOURCE, repo.to_iso(now - timedelta(hours=refresh_hours))),
    ).fetchall()

    # Prioridad por competición (odds_priority) y, dentro de ella, los partidos más próximos primero.
    rows = sorted(rows, key=lambda r: comps[r["code"]].get("odds_priority", 5))
    n_matches = n_rows = 0
    for r in rows:
        try:
            items = client.get("odds", fixture=r["source_match_id"])["response"]
        except ApiError as e:
            log.warning("odds %s: %s", r["source_match_id"], e)
            continue
        captured_at = repo.utc_now()
        for item in items:
            n_rows += repo.insert_odds(conn, odds_rows(r["id"], item, captured_at))
        n_matches += bool(items)
        conn.commit()
    return n_matches, n_rows


def collect_details(client: ApiFootball, conn: sqlite3.Connection, codes: list[str] | None = None,
                    limit: int | None = None) -> int:
    """Descarga detalles de partidos terminados que aún no los tienen (más recientes primero)."""
    codes = codes or [c for c, v in config.settings()["competitions"].items() if v["type"] == "league"]
    rows = conn.execute(
        f"""SELECT ms.source_match_id FROM match_sources ms
            JOIN matches m ON m.id = ms.match_id
            JOIN competitions c ON c.id = m.competition_id
            WHERE ms.source = ? AND ms.details_fetched_at IS NULL AND m.status = 'finished'
              AND c.code IN ({",".join("?" * len(codes))})
            ORDER BY m.kickoff_utc DESC""",
        (SOURCE, *codes),
    ).fetchall()
    n = 0
    for r in rows[:limit]:
        try:
            items = client.get("fixtures", id=r["source_match_id"])["response"]
        except ApiError as e:
            log.warning("fixture %s: %s", r["source_match_id"], e)
            continue
        try:
            for item in items:
                store_fixture_details(conn, item)
        except Exception:
            # Un partido con datos raros no debe frenar el resto; la respuesta cruda queda en data/raw.
            conn.rollback()
            log.exception("fixture %s: error al guardar detalles", r["source_match_id"])
            continue
        conn.commit()
        n += 1
    return n


def backfill_season(client: ApiFootball, conn: sqlite3.Connection, code: str, season: int) -> int:
    """Calendario completo de una temporada (plan Free: 2022-2024)."""
    league_id = config.settings()["competitions"][code]["api_football_id"]
    items = client.get("fixtures", league=league_id, season=season)["response"]
    n = sum(1 for item in items if store_fixture(conn, item))
    conn.commit()
    return n


def backfill_pending(client: ApiFootball, conn: sqlite3.Connection, limit: int) -> list[str]:
    """Carga temporadas pendientes de config (api_football.backfill), hasta `limit` por ejecución."""
    done = []
    for code, season in config.settings()["api_football"].get("backfill", []):
        if len(done) >= limit:
            break
        have = conn.execute(
            """SELECT 1 FROM matches m JOIN competitions c ON c.id = m.competition_id
               WHERE c.code = ? AND m.season = ? LIMIT 1""", (code, str(season))).fetchone()
        if have:
            continue
        n = backfill_season(client, conn, code, season)
        done.append(f"{code} {season}: {n}")
    return done


def run_daily(conn: sqlite3.Connection, client: ApiFootball) -> dict:
    cfg = config.settings()["api_football"]
    today = datetime.now(timezone.utc).date()
    dates = [(today + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
    summary = {"start_remaining": client.remaining}
    try:
        # El calendario va primero porque las cuotas se piden por partido ya conocido.
        summary["fixtures"] = collect_fixtures_by_date(client, conn, dates)
        summary["odds_matches"], summary["odds_rows"] = collect_odds(client, conn, cfg["odds_horizon_hours"])
        summary["backfill"] = backfill_pending(client, conn, cfg.get("backfill_per_run", 0))
        summary["details"] = collect_details(client, conn)
    except BudgetExhausted as e:
        log.info("Presupuesto agotado: %s", e)
    summary["end_remaining"] = client.remaining
    return summary
