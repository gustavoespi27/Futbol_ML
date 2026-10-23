"""Repositorio SQLite para persistencia de preferencias de usuario.

Maneja la inicialización idempotente de la tabla `agent_user_preferences`
y las operaciones CRUD sin interferir con las tablas existentes de footy.
"""

import json
import sqlite3

from footy.db.repository import utc_now
from footy_agents.schemas import UserPreferences

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS agent_user_preferences (
    user_id TEXT PRIMARY KEY,
    favorite_teams TEXT NOT NULL DEFAULT '[]',
    favorite_leagues TEXT NOT NULL DEFAULT '[]',
    risk_profile TEXT NOT NULL DEFAULT 'moderate',
    bankroll REAL NOT NULL DEFAULT 1000.0,
    updated_at TEXT NOT NULL
);
"""


def init_preferences_table(conn: sqlite3.Connection) -> None:
    """Crea la tabla de preferencias si no existe."""
    conn.execute(TABLE_DDL)
    conn.commit()


def get_preferences(conn: sqlite3.Connection, user_id: str = "default") -> UserPreferences:
    """Obtiene las preferencias de un usuario. Si no existe, retorna una configuración por defecto."""
    init_preferences_table(conn)
    row = conn.execute(
        "SELECT favorite_teams, favorite_leagues, risk_profile, bankroll, updated_at "
        "FROM agent_user_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return UserPreferences(user_id=user_id)
    # acceso por posición: funciona igual con sqlite3.Row que con tuplas
    return UserPreferences(
        user_id=user_id,
        favorite_teams=json.loads(row[0]),
        favorite_leagues=json.loads(row[1]),
        risk_profile=row[2],
        bankroll=float(row[3]),
        updated_at=row[4],
    )


def save_preferences(conn: sqlite3.Connection, prefs: UserPreferences) -> None:
    """Guarda o actualiza las preferencias de un usuario."""
    init_preferences_table(conn)
    conn.execute(
        """
        INSERT INTO agent_user_preferences (
            user_id, favorite_teams, favorite_leagues, risk_profile, bankroll, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            favorite_teams = excluded.favorite_teams,
            favorite_leagues = excluded.favorite_leagues,
            risk_profile = excluded.risk_profile,
            bankroll = excluded.bankroll,
            updated_at = excluded.updated_at
        """,
        (
            prefs.user_id,
            json.dumps(prefs.favorite_teams, ensure_ascii=False),
            json.dumps(prefs.favorite_leagues, ensure_ascii=False),
            prefs.risk_profile,
            float(prefs.bankroll),
            utc_now(),
        ),
    )
    conn.commit()
