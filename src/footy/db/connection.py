"""Conexión a SQLite e inicialización idempotente del esquema."""

import sqlite3
import threading
from pathlib import Path

from footy import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Bases en disco cuyo esquema ya se aplicó en este proceso: el DDL (15+ CREATE ... IF NOT EXISTS) se ejecuta una sola
# vez por proceso en vez de en cada conexión.
_initialized: set[str] = set()
_init_lock = threading.Lock()
_schema_sql: str | None = None


def _schema() -> str:
    global _schema_sql
    if _schema_sql is None:
        _schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    return _schema_sql


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Abre la base (creándola si no existe) y aplica el esquema.

    Las bases en disco usan WAL y busy_timeout: el dashboard puede leer mientras la tarea diaria escribe sin
    "database is locked". Las bases ":memory:" son siempre nuevas, así que reciben el esquema en cada conexión.
    """
    db_path = Path(db_path) if db_path else config.path("database")
    memory = str(db_path) == ":memory:"
    if not memory:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if memory:
        conn.executescript(_schema())
        return conn
    conn.execute("PRAGMA busy_timeout = 5000")
    key = str(db_path.resolve())
    if key not in _initialized:
        with _init_lock:
            if key not in _initialized:
                conn.execute("PRAGMA journal_mode = WAL")      # persistente: queda guardado en el archivo
                conn.executescript(_schema())
                _initialized.add(key)
    return conn
