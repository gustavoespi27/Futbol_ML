"""Conexión a SQLite e inicialización idempotente del esquema."""

import sqlite3
from pathlib import Path

from footy import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Abre la base (creándola si no existe) y aplica el esquema."""
    db_path = Path(db_path) if db_path else config.path("database")
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn
