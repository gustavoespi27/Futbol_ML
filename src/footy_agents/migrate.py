"""Migraciones idempotentes de las tablas propias del agente (nunca toca el esquema de footy)."""

import sqlite3


def add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Agrega la columna si falta. Seguro con procesos simultáneos (p. ej. dos vigías): si otro la agregó
    entre la consulta y el ALTER, el estado final es el esperado y no se trata como error."""
    if column in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
