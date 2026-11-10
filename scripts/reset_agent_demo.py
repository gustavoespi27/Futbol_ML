"""Vacía solo seis tablas de demo del agente; sin --yes muestra los conteos, sin borrar filas."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from footy import config

DEMO_TABLES = (
    "agent_alerts",
    "agent_watches",
    "agent_watch_state",
    "agent_watch_log",
    "agent_runs",
    "agent_chat_memory",
)


def reset(conn: sqlite3.Connection, confirmed: bool = False) -> dict[str, int]:
    """Lista cerrada, DELETE transaccional; ni DROP, preferencias, secuencias ni comodines."""
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    tables = [table for table in DEMO_TABLES if table in existing]

    def authorize(action: int, table: str | None, column: str | None, db: str | None, trigger: str | None) -> int:
        if action == sqlite3.SQLITE_DELETE:
            return sqlite3.SQLITE_OK if confirmed and table in DEMO_TABLES else sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DROP_TABLE):
            return sqlite3.SQLITE_DENY  # también impide efectos de triggers sobre preferencias/motor
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorize)
    try:
        if not confirmed:
            return {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
            for table in tables:
                conn.execute(f'DELETE FROM "{table}"')
        return counts
    finally:
        conn.set_authorizer(None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Confirmar el borrado de filas de las seis tablas indicadas")
    parser.add_argument("--database", type=Path, help="Base existente; por defecto, la configurada en la aplicación")
    args = parser.parse_args(argv)
    path = args.database or config.path("database")
    if not path.is_file():
        print(f"La base no existe: {path}. No se creó ni se borró nada.")
        return 0
    # Excepción administrativa exigida por el reset: connect() del motor inicializa schema y WAL.
    # Abrir solo un archivo existente evita crear tablas del motor y permite una simulación de solo lectura.
    mode = "rw" if args.yes else "ro"
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode={mode}", uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        counts = reset(conn, args.yes)
    print("BORRADO CONFIRMADO" if args.yes else "SIMULACIÓN: no se borraron filas")
    for table, count in counts.items():
        noun = "fila" if count == 1 else "filas"
        action = ("borrada" if count == 1 else "borradas") if args.yes else "por borrar"
        print(f"{table}: {count} {noun} {action}")
    print("Preferencias, otras tablas del agente y tablas del motor conservadas. No se modifica sqlite_sequence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
