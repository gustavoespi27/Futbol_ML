"""Memoria personalizada: lo que el Míster va aprendiendo del usuario a partir de sus conversaciones.

Se aprende de forma determinista, sin LLM, de cuatro señales:
- su nombre («me llamo Gustavo», «soy Gustavo»; «olvida mi nombre» lo borra);
- lo que el usuario dice de sí mismo («soy hincha de Colo Colo», «ya no sigo a X»), resuelto al nombre canónico;
- los equipos y ligas que consulta (entidades de las herramientas del turno);
- los temas que más pregunta (análisis, valor, tablas, forma, banca).
Cada ítem tiene un peso; lo dicho explícitamente pesa más que lo consultado. El resumen vuelve al prompt como
contexto («Lo que sabes del usuario»), nunca como cifras. El usuario puede ver y borrar cada recuerdo.
"""

import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable

from footy.db.repository import utc_now
from footy_agents.names import normalize_name
from footy_agents.schemas import MemoryItem

STATED_WEIGHT = 5.0            # «soy hincha de…» vale como cinco consultas
CONSULTED_WEIGHT = 1.0
MIN_WEIGHT_FOR_PROMPT = 2.0    # una consulta suelta no define un gusto
PROMPT_ITEMS = 4

TOPICS = {
    "analyze_match": "análisis de partidos", "simulate_match": "simulaciones de cruces",
    "get_value_bets": "apuestas con valor",
    "get_recommendations": "las recomendaciones de la máquina", "get_league_standings": "tablas de posiciones",
    "get_team_form": "cómo llegan los equipos", "get_stake_limits": "manejo de la banca",
    "get_system_performance": "el rendimiento del sistema", "get_upcoming_matches": "el calendario",
}
_TEAM = r"(?:al |a )?((?:el |la |los |las )?[^.,;!?]+?)"
_END = r"(?=\s+(?:y|pero|porque|aunque)\b|[.,;!?]|$)"
LIKE = re.compile(r"\b(?:soy (?:hincha|fan|fanatico|seguidor|del)|mi equipo es|me gusta(?:n)?(?: mucho)?|"
                  r"sigo|apoyo|simpatizo con)\s+(?:de\s+|del\s+)?" + _TEAM + _END)
DISLIKE = re.compile(r"\b(?:ya no (?:sigo|soy hincha de|me gusta(?:n)?)|no me gusta(?:n)?|no sigo|"
                     r"olvida(?:te de)?|deja de recordar)\s+(?:de\s+|del\s+)?" + _TEAM + _END)

_WORD = r"[a-záéíóúñü]+"
NAME_STOP = {"de", "del", "el", "la", "los", "las", "y", "e", "un", "una", "hincha", "fan", "fanatico", "fanático",
             "seguidor", "nuevo", "nueva", "yo", "tu", "tú", "muy", "bien", "el", "hoy", "chileno", "chilena"}
NAME = re.compile(rf"\b(?:me llamo|mi nombre es|llamame|llámame)\s+({_WORD})(?:\s+({_WORD}))?", re.I)
NAME_SOY = re.compile(r"\b(?i:soy)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñü]+)\b")          # «soy Gustavo»: solo con mayúscula
FORGET_NAME = re.compile(r"\b(?:olvida|borra)\s+mi\s+nombre\b", re.I)
NAME_KEY = "nombre"

DDL = """
CREATE TABLE IF NOT EXISTS agent_user_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('team', 'league', 'topic', 'name')),
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    weight REAL NOT NULL,
    stated INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, kind, key)
);
CREATE INDEX IF NOT EXISTS idx_agent_user_memory_user ON agent_user_memory (user_id, weight);
"""


def init_tables(conn: sqlite3.Connection) -> None:
    def legacy() -> bool:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'agent_user_memory'").fetchone()
        return bool(row) and "'name'" not in row[0]

    if legacy():
        # Tabla anterior sin el tipo «name»: se reconstruye con sus filas en una transacción exclusiva, así otra
        # conexión (el navegador consultando en paralelo) no ve la tabla a medio migrar ni escribe en la vieja.
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        try:
            if legacy():
                conn.execute("ALTER TABLE agent_user_memory RENAME TO agent_user_memory_old")
                conn.execute("DROP INDEX IF EXISTS idx_agent_user_memory_user")
                for statement in filter(str.strip, DDL.split(";")):
                    conn.execute(statement)
                conn.execute("INSERT INTO agent_user_memory SELECT * FROM agent_user_memory_old")
                conn.execute("DROP TABLE agent_user_memory_old")
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
    conn.executescript(DDL)


def user_name(message: str) -> str | None:
    """Nombre que el usuario da de sí mismo, con mayúscula inicial; None si no se presenta."""
    m = NAME.search(message)
    words = [w for w in (m.groups() if m else ()) if w]
    if not words:
        soy = NAME_SOY.search(message)
        words = [soy[1]] if soy else []
    words = words[:1] + [w for w in words[1:] if w.lower() not in NAME_STOP]
    if not words or words[0].lower() in NAME_STOP:
        return None
    return " ".join(w.capitalize() for w in words)


def name(conn: sqlite3.Connection, user_id: str) -> str:
    init_tables(conn)
    row = conn.execute("SELECT label FROM agent_user_memory WHERE user_id = ? AND kind = 'name'", (user_id,)).fetchone()
    return row[0] if row else ""


def _bump(conn: sqlite3.Connection, user_id: str, kind: str, label: str, weight: float, stated: bool) -> None:
    conn.execute(
        "INSERT INTO agent_user_memory (user_id, kind, key, label, weight, stated, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (user_id, kind, key) DO UPDATE SET "
        "weight = weight + excluded.weight, stated = MAX(stated, excluded.stated), label = excluded.label, "
        "updated_at = excluded.updated_at",
        (user_id, kind, normalize_name(label), label, weight, int(stated), utc_now()))


def _fold(text: str) -> str:
    """Minúsculas sin tildes, conservando la puntuación que marca dónde termina el nombre del equipo."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def statements(message: str) -> tuple[list[str], list[str]]:
    """Equipos que el usuario dice que sigue y los que pide olvidar (texto tal cual, sin resolver)."""
    text = _fold(message)
    dislikes = [m.strip() for m in DISLIKE.findall(text)]
    likes = [m.strip() for m in LIKE.findall(DISLIKE.sub(" ", text))]
    return [s for s in likes if s], [s for s in dislikes if s]


def _resolved(raw: str, resolve: Callable[[str], str | None]) -> str | None:
    """Prueba el nombre tal cual («la U» es un apodo) y sin artículo («el Colo Colo»)."""
    bare = re.sub(r"^(?:el|la|los|las) ", "", raw)
    return resolve(raw) or (resolve(bare) if bare != raw else None)


def learn(conn: sqlite3.Connection, user_id: str, message: str, tools_used: Iterable[str], consulted: dict,
          resolve: Callable[[str], str | None]) -> list[str]:
    """Actualiza la memoria con un turno. Devuelve qué aprendió (para pruebas y bitácora)."""
    init_tables(conn)
    learned: list[str] = []
    if FORGET_NAME.search(message):
        conn.execute("DELETE FROM agent_user_memory WHERE user_id = ? AND kind = 'name'", (user_id,))
        learned.append("olvida el nombre")
    elif given := user_name(message):
        conn.execute("INSERT INTO agent_user_memory (user_id, kind, key, label, weight, stated, updated_at) "
                     "VALUES (?, 'name', ?, ?, 0, 1, ?) ON CONFLICT (user_id, kind, key) DO UPDATE SET "
                     "label = excluded.label, updated_at = excluded.updated_at", (user_id, NAME_KEY, given, utc_now()))
        learned.append(f"se llama {given}")
    likes, dislikes = statements(message)
    for raw in dislikes:
        team = _resolved(raw, resolve)
        if team:
            conn.execute("DELETE FROM agent_user_memory WHERE user_id = ? AND kind = 'team' AND key = ?",
                         (user_id, normalize_name(team)))
            learned.append(f"olvida {team}")
    for raw in likes:
        team = _resolved(raw, resolve)
        if team:
            _bump(conn, user_id, "team", team, STATED_WEIGHT, stated=True)
            learned.append(f"sigue a {team}")
    for team in {consulted.get(k) for k in ("home", "away", "team")} - {None}:
        _bump(conn, user_id, "team", team, CONSULTED_WEIGHT, stated=False)
        learned.append(f"consultó {team}")
    if consulted.get("league_name"):
        _bump(conn, user_id, "league", consulted["league_name"], CONSULTED_WEIGHT, stated=False)
        learned.append(f"liga {consulted['league_name']}")
    for tool in dict.fromkeys(tools_used):
        if tool in TOPICS:
            _bump(conn, user_id, "topic", TOPICS[tool], CONSULTED_WEIGHT, stated=False)
    conn.commit()
    return learned


def items(conn: sqlite3.Connection, user_id: str) -> list[MemoryItem]:
    init_tables(conn)
    rows = conn.execute("SELECT id, kind, label, weight, stated, updated_at FROM agent_user_memory "
                        "WHERE user_id = ? ORDER BY kind = 'name' DESC, stated DESC, weight DESC, updated_at DESC",
        (user_id,)).fetchall()
    return [MemoryItem(id=r[0], kind=r[1], label=r[2], weight=r[3], stated=bool(r[4]), updated_at=r[5])
            for r in rows]


def prompt_summary(conn: sqlite3.Connection, user_id: str) -> str:
    """Una línea para el prompt: solo gustos con peso suficiente; nada si todavía no sabe nada."""
    rows = [i for i in items(conn, user_id) if i.stated or i.weight >= MIN_WEIGHT_FOR_PROMPT]
    names = [i.label for i in rows if i.kind == "name"]
    stated = [i.label for i in rows if i.kind == "team" and i.stated][:PROMPT_ITEMS]
    teams = [i.label for i in rows if i.kind == "team" and not i.stated][:PROMPT_ITEMS]
    leagues = [i.label for i in rows if i.kind == "league"][:PROMPT_ITEMS]
    topics = [i.label for i in rows if i.kind == "topic"][:2]
    parts = ([f"se llama {names[0]}"] if names else []) + \
            ([f"dijo que sigue a {', '.join(stated)}"] if stated else []) + \
            ([f"consulta seguido a {', '.join(teams)}"] if teams else []) + \
            ([f"le interesan {', '.join(leagues)}"] if leagues else []) + \
            ([f"suele preguntar por {' y '.join(topics)}"] if topics else [])
    return "; ".join(parts)


def forget_item(conn: sqlite3.Connection, user_id: str, item_id: int) -> bool:
    init_tables(conn)
    cur = conn.execute("DELETE FROM agent_user_memory WHERE id = ? AND user_id = ?", (item_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def forget_all(conn: sqlite3.Connection, user_id: str) -> None:
    init_tables(conn)
    conn.execute("DELETE FROM agent_user_memory WHERE user_id = ?", (user_id,))
    conn.commit()
