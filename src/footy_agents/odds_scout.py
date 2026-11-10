"""Ojeador determinista: precios ofrecidos ESPN; nunca una referencia alternativa a Pinnacle."""

# El cliente ESPN se importa solo al actuar: sin candidatos, no se cargan ni modelos ni cliente de red.
import json
import logging
import math
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from footy import config
from footy.db.connection import connect
from footy.db.repository import insert_odds
from footy_agents.scout_schemas import ScoutDecision, ScoutPerception, ScoutRun

log = logging.getLogger(__name__)


def american_to_decimal(text: str | int | float) -> float:
    """Convierte una cuota americana finita, distinta de cero, sin inferir precios ausentes."""
    if isinstance(text, bool):
        raise ValueError("Cuota americana inválida")
    try:
        value = float(str(text).strip().replace("−", "-"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Cuota americana inválida") from exc
    if not math.isfinite(value) or value == 0:
        raise ValueError("Cuota americana no finita o cero")
    price = round(1 + (value / 100 if value > 0 else 100 / abs(value)), 3)
    if price <= 1:
        raise ValueError("Precio decimal debe superar uno")
    return price


def _moneyline(offer: dict, side: str) -> Any:
    value = (offer.get("moneyline") or {}).get(side) or {}
    for stage in ("close", "open"):
        odds = (value.get(stage) or {}).get("odds")
        if odds is not None:
            return odds
    if side == "draw":
        return (offer.get("drawOdds") or {}).get("moneyLine")
    return None


def parse_event_odds(event: dict, now: datetime | None = None, rejected: list[str] | None = None) -> list[dict]:
    """Filas sin match_id: act lo asigna exclusivamente mediante match_sources, nunca por nombres."""
    now = now or datetime.now(timezone.utc)
    reasons = rejected if rejected is not None else []
    rows: list[dict] = []
    competitions = event.get("competitions") or []
    if not competitions or not isinstance(competitions[0], dict):
        reasons.append("Evento sin competición")
        return rows
    if event.get("date"):
        try:
            kickoff = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            if kickoff.tzinfo is None or kickoff <= now:
                reasons.append("Evento iniciado o fecha sin zona")
                return rows
        except (TypeError, ValueError):
            reasons.append("Fecha de evento inválida")
            return rows
    for offer in competitions[0].get("odds") or []:
        if not isinstance(offer, dict):
            reasons.append("Oferta ausente")
            continue
        book = (offer.get("provider") or {}).get("name")
        if not isinstance(book, str) or not book.strip():
            reasons.append("Oferta sin proveedor")
            continue
        if book.strip().casefold() == "pinnacle":
            reasons.append("ESPN solo aporta precios ofrecidos; no publica la referencia Pinnacle")
            continue
        base = {
            "source": "espn_odds",
            "bookmaker": book.strip(),
            "captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "is_closing": 0,
        }
        try:
            prices = [american_to_decimal(_moneyline(offer, side)) for side in ("home", "draw", "away")]
            margin = sum(1 / price for price in prices)
            if not 1 <= margin <= 1.25:
                raise ValueError(f"Margen 1X2 fuera de rango: {margin:.4f}")
            rows.extend(
                {**base, "market": "1X2", "line": 0, "selection": selection, "price": price}
                for selection, price in zip(("H", "D", "A"), prices)
            )
        except (ValueError, TypeError, AttributeError) as exc:
            reasons.append(f"{book}: 1X2 descartado: {exc}")
        try:
            line = float(offer["overUnder"])
            totals = offer.get("total") or {}
            prices = []
            for side, key in (("over", "overOdds"), ("under", "underOdds")):
                stages = totals.get(side) or {}
                stage = stages.get("close") or stages.get("open") or {}
                if stage.get("line") and float(str(stage["line"]).lstrip("ou")) != line:
                    raise ValueError("Líneas OU distintas")
                prices.append(american_to_decimal(stage.get("odds", offer.get(key))))
            over, under = prices
            if not math.isfinite(line) or line <= 0:
                raise ValueError("Línea OU inválida")
            rows.extend(
                {**base, "market": "OU", "line": line, "selection": selection, "price": price}
                for selection, price in (("OVER", over), ("UNDER", under))
            )
        except (KeyError, ValueError, TypeError):
            reasons.append(f"{book}: OU sin línea y ambos precios válidos")
    for reason in reasons:
        log.debug("Evento %s: %s", event.get("id"), reason)
    return rows


MAX_ESPN_REQUESTS = 40
ESPN_TZ = ZoneInfo("America/New_York")
DDL = """CREATE TABLE IF NOT EXISTS agent_scout_log (
    id INTEGER PRIMARY KEY, run_at TEXT NOT NULL, perceived INTEGER NOT NULL,
    decisions TEXT NOT NULL, actions INTEGER NOT NULL, inserted INTEGER NOT NULL, elapsed_ms REAL NOT NULL
)"""


def init_tables(conn: sqlite3.Connection) -> None:
    outer = conn.in_transaction
    conn.execute(DDL)
    if not outer:
        conn.commit()


def upcoming(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    rows = conn.execute(
        """SELECT m.id, h.name, a.name, c.code, m.kickoff_utc
        FROM matches m JOIN competitions c ON c.id=m.competition_id
        JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
        WHERE m.status='scheduled' AND m.kickoff_utc > ? AND m.kickoff_utc <= ?
        ORDER BY m.kickoff_utc,m.id""",
        (now.strftime("%Y-%m-%dT%H:%M:%SZ"), (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")),
    ).fetchall()
    return [dict(zip(("match_id", "home", "away", "league", "kickoff"), row)) for row in rows]


def perceive(conn: sqlite3.Connection, matches: list[dict], now: datetime) -> list[ScoutPerception]:
    """Solo lectura; favoritos de todos los usuarios, sin inicializar ni modificar preferencias."""
    from footy_agents.names import normalize_name

    favorites: set[str] = set()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='agent_user_preferences'").fetchone():
        for row in conn.execute("SELECT favorite_teams,favorite_leagues FROM agent_user_preferences"):
            favorites.update(normalize_name(v) for raw in row for v in json.loads(raw))
    result = []
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    comps = config.settings()["competitions"]
    for match in matches:
        kickoff = datetime.fromisoformat(match["kickoff"].replace("Z", "+00:00"))
        id_ = match.get("match_id") or int(match["ref"][2:])
        if kickoff <= now:
            continue
        prices = conn.execute(
            """SELECT bookmaker,source,captured_at FROM odds
            WHERE match_id=? AND captured_at<=? AND captured_at<?""",
            (id_, stamp, match["kickoff"]),
        ).fetchall()
        event = conn.execute(
            "SELECT source_match_id FROM match_sources WHERE source='espn' AND match_id=? "
            "ORDER BY source_match_id LIMIT 1",
            (id_,),
        ).fetchone()
        captures = [r[2] for r in prices if r[1] == "espn_odds"]
        result.append(
            ScoutPerception(
                match_id=id_,
                home=match["home"],
                away=match["away"],
                league=match["league"],
                kickoff=match["kickoff"],
                hours_to_kickoff=(kickoff - now).total_seconds() / 3600,
                favorite=bool({normalize_name(str(match[k])) for k in ("home", "away", "league")} & favorites),
                has_odds=bool(prices),
                has_pinnacle=any(r[0] == "Pinnacle" for r in prices),
                last_capture=max(captures) if captures else None,
                event_id=str(event[0]) if event else None,
                slug=comps.get(match["league"], {}).get("espn"),
                espn_date=kickoff.astimezone(ESPN_TZ).strftime("%Y%m%d"),
            )
        )
    return result


def plan(
    perception: list[ScoutPerception], budget: int, now: datetime, refresh_hours: float | None = None
) -> list[ScoutDecision]:
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0 or budget > MAX_ESPN_REQUESTS:
        raise ValueError("Presupuesto ESPN fuera de rango")
    chosen: set[tuple[str, str]] = set()
    decisions = []
    for p in sorted(perception, key=lambda p: (p.hours_to_kickoff, not p.favorite, p.has_odds, p.match_id)):
        if not p.has_pinnacle:
            decisions.append(
                ScoutDecision(
                    match_id=p.match_id,
                    selected=False,
                    source="api_football",
                    reason="Pinnacle no disponible: API-Football reservado para la ingesta diaria",
                )
            )
        ttl = refresh_hours if refresh_hours is not None else 1 if p.hours_to_kickoff < 6 else 6
        group = (p.slug, p.espn_date) if p.slug else None
        reason = "Captura ESPN ausente o vencida"
        selected = True
        if not p.event_id or not p.slug:
            selected, reason = False, "Sin id ESPN o sin slug: no hay calce exacto"
        elif (
            p.last_capture
            and (now - datetime.fromisoformat(p.last_capture.replace("Z", "+00:00"))).total_seconds() < ttl * 3600
        ):
            selected, reason = False, "Captura ESPN reciente: no se repite la petición"
        elif group not in chosen and len(chosen) >= budget:
            selected, reason = False, "Presupuesto de scoreboards agotado"
        if selected and group:
            chosen.add(group)
        decisions.append(
            ScoutDecision(
                match_id=p.match_id, selected=selected, source="espn", reason=reason, group=group, refresh_hours=ttl
            )
        )
    return decisions


def act(
    conn: sqlite3.Connection,
    perception: list[ScoutPerception],
    decisions: list[ScoutDecision],
    client: Any = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[int, int]:
    clock = clock or (lambda: datetime.now(timezone.utc))
    selected = [d for d in decisions if d.selected and d.source == "espn"]
    if not selected:
        return 0, 0
    from footy.ingest.espn import Espn, EspnUnavailable

    client = client or Espn()
    if isinstance(client, Espn):
        client.session.headers["User-Agent"] = "Futbol_ML/1.0"
    by_id = {p.match_id: p for p in perception}
    groups = list(dict.fromkeys(d.group for d in selected))
    actions, inserted = 0, 0
    for group in groups:
        actions += 1
        try:
            events = client.scoreboard(*group)
        except EspnUnavailable as exc:
            for d in selected:
                if d.group == group:
                    d.reason = f"ESPN no disponible: {exc}"
            continue
        capture = clock()
        event_map = {str(e.get("id")): e for e in events if isinstance(e, dict)}
        for d in selected:
            if d.group != group:
                continue
            p = by_id[d.match_id]
            if capture >= datetime.fromisoformat(p.kickoff.replace("Z", "+00:00")):
                d.reason = "Partido iniciado durante la consulta: captura descartada"
                continue
            event = event_map.get(p.event_id)
            if event is None:
                d.reason = "El scoreboard no contiene el id ESPN exacto"
                continue
            rejected: list[str] = []
            rows = parse_event_odds(event, capture, rejected)
            if not rows:
                d.reason = "Sin precios válidos: " + "; ".join(rejected)
                continue
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                recent = conn.execute(
                    "SELECT MAX(captured_at) FROM odds WHERE match_id=? AND source='espn_odds'", (p.match_id,)
                ).fetchone()[0]
                if (
                    recent
                    and (capture - datetime.fromisoformat(recent.replace("Z", "+00:00"))).total_seconds()
                    < d.refresh_hours * 3600
                ):
                    d.reason = "Otra ejecución ya publicó una captura reciente"
                    continue
                inserted += insert_odds(conn, [{**r, "match_id": p.match_id} for r in rows])
            d.reason = f"Captura publicada: {len(rows)} precios ofrecidos; no son referencia justa"
    return actions, inserted


def run(
    conn: sqlite3.Connection,
    now: datetime | None = None,
    budget: int = MAX_ESPN_REQUESTS,
    matches: list[dict] | None = None,
    client: Any = None,
    refresh_hours: float | None = None,
    dry_run: bool = False,
) -> ScoutRun:
    start = time.perf_counter()
    if conn.in_transaction:
        raise ValueError("El Ojeador requiere una conexión sin transacción ajena")
    fixed_now = now
    now = now or datetime.now(timezone.utc)
    perception = perceive(conn, upcoming(conn, now) if matches is None else matches, now)
    decisions = plan(perception, budget, now, refresh_hours)
    result = ScoutRun(
        run_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"), perceived=len(perception), perception=perception, decisions=decisions
    )
    if not dry_run:
        init_tables(conn)
        result.actions, result.inserted = act(
            conn, perception, decisions, client, (lambda: fixed_now) if fixed_now else None
        )
    result.elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    if not dry_run:
        with conn:
            cursor = conn.execute(
                "INSERT INTO agent_scout_log(run_at,perceived,decisions,actions,inserted,elapsed_ms) "
                "VALUES(?,?,?,?,?,?)",
                (
                    result.run_at,
                    result.perceived,
                    json.dumps([d.model_dump() for d in decisions], ensure_ascii=False),
                    result.actions,
                    result.inserted,
                    result.elapsed_ms,
                ),
            )
            result.id = cursor.lastrowid
        if result.inserted:
            publish_changes(conn)
    return result


def publish_changes(conn: sqlite3.Connection) -> None:
    """Invalida solo la base real; una prueba o CLI aislada nunca toca la caché global ni la red."""
    filename = conn.execute("PRAGMA database_list").fetchone()[2]
    if not filename or Path(filename).resolve() != config.path("database").resolve():
        return
    import requests

    from footy.web import service
    from footy.web.services import snapshots

    try:
        snapshots.advance_revision()
        service.clear_caches()
        requests.post("http://127.0.0.1:8000/api/refresh", timeout=3)
    except (OSError, requests.RequestException):
        log.warning("Cuotas publicadas; panel cerrado o refresco diferido", exc_info=True)


def run_safely() -> None:
    try:
        with closing(connect()) as conn:
            run(conn)
    except (sqlite3.Error, ValueError, KeyError):
        log.exception("No se pudo ejecutar el Ojeador; el ciclo principal continúa")
