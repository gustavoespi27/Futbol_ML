"""Objetivos persistentes y consultas de alertas; únicamente escribe tablas agent_*."""

import json
import sqlite3

from footy.db.repository import utc_now
from footy_agents.watch_schemas import CONDITION_LABELS, Alert, Watch, WatchArgs, WatchRun

DDL = """
CREATE TABLE IF NOT EXISTS agent_watches (
 id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, match_id INTEGER, team TEXT,
 condition TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, fulfilled_at TEXT,
 CHECK ((match_id IS NULL) != (team IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS agent_watch_active_match
 ON agent_watches(user_id, match_id, condition) WHERE status='active' AND match_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS agent_watch_active_team
 ON agent_watches(user_id, team, condition) WHERE status='active' AND team IS NOT NULL;
CREATE TABLE IF NOT EXISTS agent_watch_state (
 match_id INTEGER PRIMARY KEY, snapshot TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_alerts (
 id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL, match_id INTEGER NOT NULL,
 watch_id INTEGER, kind TEXT NOT NULL, priority INTEGER NOT NULL, facts TEXT NOT NULL, text TEXT NOT NULL,
 read INTEGER NOT NULL DEFAULT 0, dedup_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS agent_alert_user ON agent_alerts(user_id, read, id);
CREATE TABLE IF NOT EXISTS agent_watch_log (
 id INTEGER PRIMARY KEY, run_at TEXT NOT NULL, perceived INTEGER NOT NULL, decisions TEXT NOT NULL,
 actions INTEGER NOT NULL, elapsed_ms REAL NOT NULL, perception TEXT NOT NULL DEFAULT '{}'
);
"""


def init_tables(conn: sqlite3.Connection) -> None:
    outer = conn.in_transaction            # dentro de la transacción del vigía no se confirma a medias
    conn.executescript(DDL)
    alert_cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_alerts)")}
    if "expires_at" not in alert_cols:
        conn.execute("ALTER TABLE agent_alerts ADD COLUMN expires_at TEXT")  # inicio del partido: deja de mostrarse
    # Descartado por el usuario: se oculta pero la fila queda, así la deduplicación no vuelve a emitir el mismo aviso.
    if "dismissed_at" not in alert_cols:
        conn.execute("ALTER TABLE agent_alerts ADD COLUMN dismissed_at TEXT")
    # Alertas previas a la columna: expiran con el inicio guardado en sus facts (solo toca filas sin fecha).
    conn.execute("UPDATE agent_alerts SET expires_at=json_extract(facts,'$.kickoff') "
                 "WHERE expires_at IS NULL AND json_extract(facts,'$.kickoff') IS NOT NULL")
    if "perception" not in {r[1] for r in conn.execute("PRAGMA table_info(agent_watch_log)")}:
        conn.execute("ALTER TABLE agent_watch_log ADD COLUMN perception TEXT NOT NULL DEFAULT '{}'")
    if not outer:
        conn.commit()                       # la migración no deja la base bloqueada para otras conexiones


def list_watches(conn: sqlite3.Connection, user_id: str) -> list[Watch]:
    init_tables(conn)
    return [
        Watch(**dict(zip(Watch.model_fields, row)))
        for row in conn.execute(
            "SELECT id,user_id,match_id,team,condition,status,created_at,fulfilled_at "
            "FROM agent_watches WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        )
    ]


def create_watch(conn: sqlite3.Connection, user_id: str, args: WatchArgs) -> dict:
    init_tables(conn)
    if args.match_id is not None:
        if not conn.execute("SELECT 1 FROM matches WHERE id=?", (args.match_id,)).fetchone():
            raise ValueError("El match_id no existe")
    elif not conn.execute("SELECT 1 FROM teams WHERE name=?", (args.team,)).fetchone():
        raise ValueError("El equipo no existe")
    with conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO agent_watches (user_id,match_id,team,condition,created_at) VALUES (?,?,?,?,?)",
            (user_id, args.match_id, args.team, args.condition, utc_now()),
        )
        created = cursor.rowcount == 1
        row = conn.execute(
            "SELECT id FROM agent_watches WHERE user_id=? AND match_id IS ? AND team IS ? "
            "AND condition=? AND status='active'",
            (user_id, args.match_id, args.team, args.condition),
        ).fetchone()
    id_ = row[0]
    target = f"partido {args.match_id}" if args.match_id is not None else args.team
    note = "Quedó vigilando" if created else "ya estaba vigilando"
    return {
        "status": "ok",
        "id": id_,
        "created": created,
        "note": note,
        "confirmation_text": f"Vigilancia {id_}: {note} {target}; {CONDITION_LABELS[args.condition]}.",
        "match_id": args.match_id,
        "team": args.team,
        "condition": args.condition,
    }


def cancel_watch(conn: sqlite3.Connection, user_id: str, id_: int) -> dict:
    init_tables(conn)
    with conn:
        row = conn.execute("SELECT status FROM agent_watches WHERE id=? AND user_id=?", (id_, user_id)).fetchone()
        if row is None:
            raise ValueError("La vigilancia no existe para este usuario")
        if row[0] == "active":
            conn.execute("UPDATE agent_watches SET status='cancelled' WHERE id=? AND user_id=?", (id_, user_id))
    return {
        "status": "ok",
        "id": id_,
        "note": "Vigilancia cancelada" if row[0] == "active" else "Ya estaba inactiva",
        "confirmation_text": f"Vigilancia {id_}: cancelada."
        if row[0] == "active"
        else f"Vigilancia {id_}: ya estaba inactiva ({row[0]}).",
    }


def alerts(conn: sqlite3.Connection, user_id: str, unread: bool = False, types: list[str] | None = None,
           now: str | None = None) -> list[Alert]:
    """Vigentes (el partido no ha empezado), las más urgentes primero."""
    init_tables(conn)
    kinds = [t for t in types or [] if t]
    rows = conn.execute(
        "SELECT id,created_at,match_id,watch_id,kind,priority,facts,text,read,expires_at FROM agent_alerts "
        "WHERE user_id=? AND (?=0 OR read=0) AND (expires_at IS NULL OR expires_at>?) AND dismissed_at IS NULL "
        f"{'AND kind IN (' + ','.join('?' * len(kinds)) + ')' if kinds else ''} "
        "ORDER BY expires_at IS NULL, expires_at, priority DESC, id DESC LIMIT 100",
        (user_id, int(unread), now or utc_now(), *kinds),
    )
    return [
        Alert(
            id=r[0],
            created_at=r[1],
            match_id=r[2],
            watch_id=r[3],
            kind=r[4],
            priority=r[5],
            facts=json.loads(r[6]),
            text=r[7],
            read=bool(r[8]),
            expires_at=r[9],
        )
        for r in rows
    ]


def mark_read(conn: sqlite3.Connection, user_id: str, id_: int) -> bool:
    init_tables(conn)
    with conn:
        return conn.execute("UPDATE agent_alerts SET read=1 WHERE id=? AND user_id=?", (id_, user_id)).rowcount == 1


def dismiss(conn: sqlite3.Connection, user_id: str, id_: int) -> bool:
    """El usuario descarta el aviso: deja de mostrarse y cuenta como leído."""
    init_tables(conn)
    with conn:
        return conn.execute("UPDATE agent_alerts SET dismissed_at=?, read=1 WHERE id=? AND user_id=? "
                            "AND dismissed_at IS NULL", (utc_now(), id_, user_id)).rowcount == 1


def mark_all_read(conn: sqlite3.Connection, user_id: str) -> int:
    init_tables(conn)
    with conn:
        return conn.execute("UPDATE agent_alerts SET read=1 WHERE user_id=? AND read=0", (user_id,)).rowcount


def recent_logs(conn: sqlite3.Connection, limit: int = 20, user_id: str = "default") -> list[WatchRun]:
    init_tables(conn)
    rows = conn.execute(
        "SELECT id,run_at,perceived,decisions,actions,elapsed_ms,perception "
        "FROM agent_watch_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    result = []
    for r in rows:
        decisions = [d for d in json.loads(r[3]) if d["user_id"] == user_id]
        result.append(
            WatchRun(
                id=r[0],
                run_at=r[1],
                perceived=r[2],
                perception=json.loads(r[6]),
                decisions=decisions,
                actions=sum(d["selected"] for d in decisions),
                elapsed_ms=r[5],
            )
        )
    return result
