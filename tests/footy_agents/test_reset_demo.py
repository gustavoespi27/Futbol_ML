"""Reset de demo: simulación, lista cerrada, base temporal y rollback de efectos fuera de alcance."""

import sqlite3

import pytest
from scripts.reset_agent_demo import DEMO_TABLES, main, reset

from footy.db.connection import connect


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "demo.sqlite"
    conn = connect(path)
    for table in (*DEMO_TABLES, "agent_user_preferences", "agent_briefing_preservado"):
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}"(id INTEGER PRIMARY KEY, value TEXT)')
        conn.execute(f'INSERT INTO "{table}" VALUES(1,?)', (f"contenido de {table}",))
    conn.execute("INSERT INTO teams(id,name,country) VALUES(1,'Chile','Chile')")
    conn.commit()
    yield path, conn
    conn.close()


def test_preview_changes_nothing(db):
    _, conn = db
    before = list(conn.iterdump())
    counts = reset(conn)
    assert counts == dict.fromkeys(DEMO_TABLES, 1)
    assert list(conn.iterdump()) == before


def test_confirmed_reset_preserves_preferences_motor_and_other_agent_tables(db):
    _, conn = db
    counts = reset(conn, confirmed=True)
    assert counts == dict.fromkeys(DEMO_TABLES, 1)
    assert all(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0 for table in DEMO_TABLES)
    assert (
        conn.execute("SELECT value FROM agent_user_preferences").fetchone()[0] == "contenido de agent_user_preferences"
    )
    assert conn.execute("SELECT COUNT(*) FROM agent_briefing_preservado").fetchone()[0] == 1
    assert tuple(conn.execute("SELECT * FROM teams").fetchone()) == (1, "Chile", "Chile")
    assert reset(conn, confirmed=True) == dict.fromkeys(DEMO_TABLES, 0)


def test_cli_requires_yes_and_does_not_create_missing_database(db, tmp_path, capsys):
    path, conn = db
    assert main(["--database", str(path)]) == 0
    assert "SIMULACIÓN" in capsys.readouterr().out
    assert conn.execute("SELECT COUNT(*) FROM agent_watches").fetchone()[0] == 1
    assert main(["--database", str(path), "--yes"]) == 0
    assert "BORRADO CONFIRMADO" in capsys.readouterr().out
    assert conn.execute("SELECT COUNT(*) FROM agent_watches").fetchone()[0] == 0
    missing = tmp_path / "missing.sqlite"
    assert main(["--database", str(missing), "--yes"]) == 0
    assert not missing.exists()


def test_missing_demo_tables_are_not_created(tmp_path):
    path = tmp_path / "partial.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE agent_runs(id INTEGER)")
        conn.execute("INSERT INTO agent_runs VALUES(1)")
        conn.commit()
        preview = path.read_bytes()
        assert main(["--database", str(path)]) == 0
        assert path.read_bytes() == preview
        assert main(["--database", str(path), "--yes"]) == 0
        assert reset(conn, confirmed=True) == {"agent_runs": 0}
        assert [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")] == ["agent_runs"]


def test_trigger_cannot_delete_preferences_and_entire_reset_rolls_back(db):
    _, conn = db
    conn.execute(
        "CREATE TRIGGER dangerous_reset AFTER DELETE ON agent_watches BEGIN DELETE FROM agent_user_preferences; END"
    )
    conn.commit()
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        reset(conn, confirmed=True)
    assert conn.execute("SELECT COUNT(*) FROM agent_alerts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM agent_watches").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM agent_user_preferences").fetchone()[0] == 1
