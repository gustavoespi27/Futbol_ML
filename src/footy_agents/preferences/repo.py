"""Repositorio SQLite para persistencia de preferencias de usuario.

Maneja la inicialización idempotente de la tabla `agent_user_preferences`
y las operaciones CRUD sin interferir con las tablas existentes de footy.
"""

import json
import sqlite3

from footy.db.repository import utc_now
from footy_agents.schemas import DEFAULT_ALERT_TYPES, UserPreferences

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


ALERT_COLUMNS = {
    "alert_types": f"TEXT NOT NULL DEFAULT '{json.dumps(DEFAULT_ALERT_TYPES)}'",
    "alerts_only_favorites": "INTEGER NOT NULL DEFAULT 0",
    "browser_notifications": "INTEGER NOT NULL DEFAULT 0",
}


def init_preferences_table(conn: sqlite3.Connection) -> None:
    """Crea la tabla de preferencias si no existe y agrega las columnas de avisos (migración idempotente)."""
    conn.execute(TABLE_DDL)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(agent_user_preferences)")}
    for column, ddl in ALERT_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE agent_user_preferences ADD COLUMN {column} {ddl}")
    conn.commit()


def get_preferences(conn: sqlite3.Connection, user_id: str = "default") -> UserPreferences:
    """Obtiene las preferencias de un usuario. Si no existe, retorna una configuración por defecto."""
    init_preferences_table(conn)
    row = conn.execute(
        "SELECT favorite_teams, favorite_leagues, risk_profile, bankroll, updated_at, alert_types, "
        "alerts_only_favorites, browser_notifications FROM agent_user_preferences WHERE user_id = ?",
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
        alert_types=json.loads(row[5]),
        alerts_only_favorites=bool(row[6]),
        browser_notifications=bool(row[7]),
    )


def save_preferences(conn: sqlite3.Connection, prefs: UserPreferences) -> None:
    """Guarda o actualiza las preferencias de un usuario."""
    init_preferences_table(conn)
    conn.execute(
        """
        INSERT INTO agent_user_preferences (
            user_id, favorite_teams, favorite_leagues, risk_profile, bankroll, updated_at,
            alert_types, alerts_only_favorites, browser_notifications
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            favorite_teams = excluded.favorite_teams,
            favorite_leagues = excluded.favorite_leagues,
            risk_profile = excluded.risk_profile,
            bankroll = excluded.bankroll,
            updated_at = excluded.updated_at,
            alert_types = excluded.alert_types,
            alerts_only_favorites = excluded.alerts_only_favorites,
            browser_notifications = excluded.browser_notifications
        """,
        (
            prefs.user_id,
            json.dumps(prefs.favorite_teams, ensure_ascii=False),
            json.dumps(prefs.favorite_leagues, ensure_ascii=False),
            prefs.risk_profile,
            float(prefs.bankroll),
            utc_now(),
            json.dumps(prefs.alert_types),
            int(prefs.alerts_only_favorites),
            int(prefs.browser_notifications),
        ),
    )
    conn.commit()
