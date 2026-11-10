"""Historial de conversaciones del chat (como los asistentes grandes): tablas propias con DDL idempotente.

Cada conversación guarda lo que el usuario vio: su pregunta y la respuesta final (o el aviso de error). Solo las
respuestas verificadas vuelven al modelo como contexto, y nunca resultados de herramientas: los datos cambian y se
vuelven a consultar. Las entidades del último turno (partido o equipo) permiten seguir el hilo al retomar una
conversación antigua.
"""

import json
import sqlite3

from footy.db.repository import utc_now
from footy_agents.schemas import Conversation, ConversationMessage

CONTEXT_TURNS = 3              # pares pregunta/respuesta que vuelven al modelo
MAX_ANSWER_CHARS = 1500        # una respuesta larga no debe llenar la ventana de contexto del modelo
TITLE_CHARS = 60

DDL = """
CREATE TABLE IF NOT EXISTS agent_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_conversations_user ON agent_conversations (user_id, updated_at);
CREATE TABLE IF NOT EXISTS agent_conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    entities TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_conversation_messages ON agent_conversation_messages (conversation_id, id);
"""


def init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def title_from(message: str) -> str:
    text = " ".join(message.split())
    return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS - 1].rstrip() + "…"


def create(conn: sqlite3.Connection, user_id: str, title: str = "Nueva conversación") -> int:
    init_tables(conn)
    now = utc_now()
    cur = conn.execute("INSERT INTO agent_conversations (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                       (user_id, title, now, now))
    conn.commit()
    return int(cur.lastrowid)


def owns(conn: sqlite3.Connection, user_id: str, conversation_id: int) -> bool:
    init_tables(conn)
    return conn.execute("SELECT 1 FROM agent_conversations WHERE id = ? AND user_id = ?",
                        (conversation_id, user_id)).fetchone() is not None


def add_turn(conn: sqlite3.Connection, user_id: str, conversation_id: int, question: str, answer: str,
             verified: bool, entities: dict | None = None) -> None:
    """Guarda la pregunta y lo que vio el usuario; la primera pregunta pasa a ser el título."""
    if not owns(conn, user_id, conversation_id):
        return
    now = utc_now()
    first = conn.execute("SELECT COUNT(*) FROM agent_conversation_messages WHERE conversation_id = ?",
                         (conversation_id,)).fetchone()[0] == 0
    conn.execute("INSERT INTO agent_conversation_messages (conversation_id, role, content, verified, created_at) "
                 "VALUES (?, 'user', ?, 1, ?)", (conversation_id, question, now))
    conn.execute("INSERT INTO agent_conversation_messages (conversation_id, role, content, verified, entities, "
                 "created_at) VALUES (?, 'assistant', ?, ?, ?, ?)",
                 (conversation_id, answer[:MAX_ANSWER_CHARS * 4], int(verified),
                  json.dumps(entities or {}, ensure_ascii=False), now))
    if first:
        conn.execute("UPDATE agent_conversations SET title = ?, updated_at = ? WHERE id = ?",
                     (title_from(question), now, conversation_id))
    else:
        conn.execute("UPDATE agent_conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
    conn.commit()


def context(conn: sqlite3.Connection, user_id: str, conversation_id: int) -> tuple[list[dict], dict]:
    """Últimos turnos verificados (más antiguos primero) y entidades del último turno de la conversación."""
    if not owns(conn, user_id, conversation_id):
        return [], {}
    rows = conn.execute("SELECT role, content, verified, entities FROM agent_conversation_messages "
                        "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                        (conversation_id, CONTEXT_TURNS * 2)).fetchall()
    entities = next((json.loads(r[3]) for r in rows if r[0] == "assistant"), {})
    turns: list[dict] = []
    pairs = list(reversed(rows))
    for question, answer in zip(pairs[::2], pairs[1::2]):
        if question[0] == "user" and answer[0] == "assistant" and answer[2] and answer[1].strip():
            turns += [{"role": "user", "content": question[1]},
                      {"role": "assistant", "content": answer[1][:MAX_ANSWER_CHARS]}]
    return turns, entities


def list_for(conn: sqlite3.Connection, user_id: str, limit: int = 30) -> list[Conversation]:
    init_tables(conn)
    rows = conn.execute(
        "SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) FROM agent_conversations c "
        "LEFT JOIN agent_conversation_messages m ON m.conversation_id = c.id WHERE c.user_id = ? "
        "GROUP BY c.id HAVING COUNT(m.id) > 0 ORDER BY c.updated_at DESC, c.id DESC LIMIT ?",
        (user_id, limit)).fetchall()
    return [Conversation(id=r[0], title=r[1], created_at=r[2], updated_at=r[3], messages=r[4] // 2) for r in rows]


def messages(conn: sqlite3.Connection, user_id: str, conversation_id: int) -> list[ConversationMessage] | None:
    if not owns(conn, user_id, conversation_id):
        return None
    rows = conn.execute("SELECT role, content, verified, created_at FROM agent_conversation_messages "
                        "WHERE conversation_id = ? ORDER BY id", (conversation_id,)).fetchall()
    return [ConversationMessage(role=r[0], content=r[1], verified=bool(r[2]), created_at=r[3]) for r in rows]


def delete(conn: sqlite3.Connection, user_id: str, conversation_id: int) -> bool:
    if not owns(conn, user_id, conversation_id):
        return False
    conn.execute("DELETE FROM agent_conversation_messages WHERE conversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM agent_conversations WHERE id = ?", (conversation_id,))
    conn.commit()
    return True
