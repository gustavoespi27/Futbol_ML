"""Memoria de conversación y bitácora de ejecuciones del agente (tablas propias, DDL idempotente).

- Memoria corta: los últimos turnos del usuario en una ventana de tiempo vuelven al LLM como contexto. Solo se guardan
  la pregunta y la respuesta final ya verificada; los resultados de herramientas no se guardan porque los datos cambian
  y deben volver a consultarse.
- Bitácora: cada turno queda registrado con sus pasos (herramientas, observaciones, desvíos, reparaciones) para
  auditar cómo decidió el agente y medirlo.
"""

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from footy.db.repository import utc_now
from footy_agents.schemas import AgentRun, ChatEvent, ToolCallRecord

MEMORY_TURNS = 3               # pares pregunta/respuesta que vuelven al modelo
MEMORY_WINDOW = timedelta(minutes=30)
MAX_ANSWER_CHARS = 1500        # una respuesta larga no debe llenar la ventana de contexto del modelo

DDL = """
CREATE TABLE IF NOT EXISTS agent_chat_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_chat_memory_user ON agent_chat_memory (user_id, created_at);
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    message TEXT NOT NULL,
    steps TEXT NOT NULL,
    iterations INTEGER NOT NULL,
    success INTEGER NOT NULL,
    elapsed_ms REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_user ON agent_runs (user_id, started_at);
"""


def init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    if "entities" not in {row[1] for row in conn.execute("PRAGMA table_info(agent_chat_memory)")}:
        conn.execute("ALTER TABLE agent_chat_memory ADD COLUMN entities TEXT NOT NULL DEFAULT '{}'")


def history(conn: sqlite3.Connection, user_id: str, now: datetime | None = None) -> list[dict]:
    """Mensajes previos (más antiguos primero) dentro de la ventana de memoria."""
    init_tables(conn)
    since = ((now or datetime.now(timezone.utc)) - MEMORY_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT question, answer FROM agent_chat_memory WHERE user_id = ? AND created_at >= ? "
        "ORDER BY id DESC LIMIT ?", (user_id, since, MEMORY_TURNS)).fetchall()
    out: list[dict] = []
    for question, answer in reversed(rows):
        if answer:
            out += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    return out


def remember(conn: sqlite3.Connection, user_id: str, question: str, answer: str,
             entities: dict | None = None) -> None:
    init_tables(conn)
    conn.execute("INSERT INTO agent_chat_memory (user_id, question, answer, created_at, entities) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (user_id, question, answer[:MAX_ANSWER_CHARS], utc_now(),
                  json.dumps(entities or {}, ensure_ascii=False)))
    conn.commit()


def recent_entities(conn: sqlite3.Connection, user_id: str, now: datetime | None = None) -> dict:
    """Última entidad consultada dentro de la misma ventana temporal y usuario."""
    init_tables(conn)
    since = ((now or datetime.now(timezone.utc)) - MEMORY_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = conn.execute("SELECT entities FROM agent_chat_memory WHERE user_id = ? AND created_at >= ? "
                       "ORDER BY id DESC LIMIT 1", (user_id, since)).fetchone()
    return json.loads(row[0]) if row else {}


def entities_from(record: ToolCallRecord) -> dict:
    """Conserva identificadores y nombres, nunca probabilidades ni precios pasados."""
    if not record.success or record.tool_name not in {
        "analyze_match", "request_odds", "find_team", "simulate_match", "get_team_form", "get_upcoming_matches",
        "get_league_standings"
    }:
        return {}
    result = record.result
    if record.tool_name == "get_league_standings":
        # «¿y los últimos?» después de una tabla: la liga consultada sigue siendo el tema.
        return {k: result[k] for k in ("league", "league_name") if isinstance(result, dict) and result.get(k)}
    if record.tool_name == "simulate_match" and isinstance(result, dict) and result.get("status") == "ambiguous":
        # Pregunta pendiente: «¿cuál Real?». La respuesta siguiente («Real Madrid») completa esta misma simulación.
        return {"clarify": {"tool": "simulate_match", "args": dict(record.arguments),
                            "options": [{"team": o["team"], "league_name": o.get("league_name", "")}
                                        for o in result.get("options", [])]}}
    if record.tool_name == "get_upcoming_matches":
        if not isinstance(result, list) or not result:
            return {"shown_ids": []}
        shown = {"shown_ids": [row["match_id"] for row in result if row.get("match_id")]}
        if len(result) != 1 and not record.arguments.get("team"):
            return shown
        result = min(result, key=lambda row: (row.get("local_date") or row.get("kickoff") or "9999",
                                             row.get("kickoff_local") or ""))
        return {**shown, **{k: result[k] for k in ("match_id", "home", "away", "league", "league_name")
                           if result.get(k) is not None}}
    if record.tool_name == "find_team":
        exact = [r for r in result if r.get("exact")]
        if len(exact) != 1:
            return {}
        result = exact[0].get("next_match") or {"team": exact[0]["team"]}
    if not isinstance(result, dict) or result.get("error"):
        return {}
    return {k: result[k] for k in ("match_id", "home", "away", "team", "league", "league_name")
            if result.get(k) is not None}


def forget(conn: sqlite3.Connection, user_id: str) -> None:
    init_tables(conn)
    conn.execute("DELETE FROM agent_chat_memory WHERE user_id = ?", (user_id,))
    conn.commit()


def steps_from(events: Iterable[ChatEvent]) -> list[dict]:
    """Resumen ordenado del turno para la bitácora (sin el texto token a token)."""
    out: list[dict] = []
    for ev in events:
        if ev.event == "step":
            out.append({"kind": ev.data["kind"], "detail": ev.data["text"]})
        elif ev.event == "tool_start":
            out.append({"kind": "tool", "detail": ev.data["tool"], "args": ev.data.get("args", {})})
        elif ev.event == "tool_result" and out and out[-1]["kind"] == "tool":
            out[-1].update(success=ev.data["success"], summary=ev.data["summary"],
                           elapsed_ms=ev.data["elapsed_ms"])
        elif ev.event == "error":
            out.append({"kind": "error", "detail": ev.data["error"]})
    return out


def log_run(conn: sqlite3.Connection, user_id: str, message: str, started_at: str, events: list[ChatEvent],
            elapsed_ms: float) -> None:
    init_tables(conn)
    done = next((ev.data for ev in reversed(events) if ev.event == "done"), {"iterations": 0, "success": False})
    continued = any(ev.event == "step" and ev.data.get("memory") == "continued"
                    for ev in events)
    memory_decision = {"kind": "memory", "detail": "Último turno y entidades" if continued
                       else "Tema nuevo: sin historial ni entidades"}
    conn.execute(
        "INSERT INTO agent_runs (user_id, started_at, message, steps, iterations, success, elapsed_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, started_at, message, json.dumps([memory_decision, *steps_from(events)],
                                                ensure_ascii=False, default=str),
         int(done["iterations"]), int(bool(done["success"])), round(elapsed_ms, 1)))
    conn.commit()


def recent_runs(conn: sqlite3.Connection, user_id: str, limit: int = 20) -> list[AgentRun]:
    init_tables(conn)
    rows = conn.execute(
        "SELECT id, started_at, message, steps, iterations, success, elapsed_ms FROM agent_runs "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    return [AgentRun(id=r[0], started_at=r[1], message=r[2], steps=json.loads(r[3]), iterations=r[4],
                     success=bool(r[5]), elapsed_ms=r[6]) for r in rows]
