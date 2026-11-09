"""Guardia pura, pausas con expiración, locks y omisión por revisión semántica."""

import pytest

from footy.db.connection import connect
from footy_agents import automation as auto


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "directory", lambda: tmp_path)
    monkeypatch.setattr(auto, "lower_priority", lambda: None)
    monkeypatch.setattr(auto, "pc_usage", lambda: (0, 0))


@pytest.mark.parametrize("cpu,state,urgent,expected", [
    (60, 0, False, False), (60.1, 0, False, True), (0, 2, False, True), (0, 3, False, True),
    (0, 4, False, True), (99, 4, True, False), (0, 1, False, False),
])
def test_defer_policy(cpu, state, urgent, expected):
    assert auto.should_defer(cpu, state, urgent=urgent) is expected


def test_pause_expires_without_manual_resume(monkeypatch):
    monkeypatch.setattr(auto.time, "time", lambda: 100)
    assert auto.pause(7200) == {"paused_until": 7300}
    assert auto.paused(7299) and not auto.paused(7300)
    auto.write_state("control", {})
    assert not auto.paused()


def test_lock_is_exclusive_and_released():
    with auto.instance_lock() as acquired:
        assert acquired
        with auto.instance_lock() as second:
            assert not second
    with auto.instance_lock() as acquired:
        assert acquired


def test_task_stores_steps_and_success():
    def work():
        auto.record_step("daily", "modelos", "omitido: sin cambios")
        return 0

    assert auto.run_task("daily", work) == 0
    state = auto.read_state("daily")
    assert state["status"] == "completa" and state["finished_at"]
    assert state["steps"][0]["status"] == "omitido: sin cambios"


def test_task_skips_on_pause_or_other_worker():
    auto.pause(7200)
    def forbidden():
        pytest.fail("No ejecutar")
    assert auto.run_task("daily", forbidden) == 0
    assert auto.read_state("daily")["reason"] == "pausa vigente"
    auto.write_state("control", {})
    with auto.instance_lock("daily"):
        assert auto.run_task("daily", forbidden) == 0
    with auto.instance_lock():
        assert auto.run_task("daily", forbidden) == 0
    assert auto.read_state("daily")["reason"] == "otra tarea está trabajando"


def test_daily_retries_but_does_not_block_urgent_prekickoff(monkeypatch):
    clock = [0]
    monkeypatch.setattr(auto.time, "time", lambda: clock[0])
    monkeypatch.setattr(auto, "pc_usage", lambda: (90 if clock[0] == 0 else 0, 0))

    def sleep(seconds):
        assert seconds == 900
        assert auto.run_task("prekickoff", lambda: 0, urgent=lambda: True) == 0
        assert auto.read_state("prekickoff")["status"] == "completa"
        clock[0] += seconds

    monkeypatch.setattr(auto.time, "sleep", sleep)
    assert auto.run_task("daily", lambda: 0) == 0
    assert clock == [900]
    assert auto.read_state("daily")["status"] == "completa"
    assert "next_retry" not in auto.read_state("daily")


def test_daily_deferral_stops_after_three_hours(monkeypatch):
    clock = [0]
    monkeypatch.setattr(auto.time, "time", lambda: clock[0])
    monkeypatch.setattr(auto, "pc_usage", lambda: (90, 0))
    monkeypatch.setattr(auto.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert auto.run_task("daily", lambda: pytest.fail("No ejecutar ocupado")) == 0
    assert clock == [10800]
    assert auto.read_state("daily")["reason"] == "límite de tres horas alcanzado"


def test_prekickoff_defers_only_without_urgent_match(monkeypatch):
    monkeypatch.setattr(auto, "pc_usage", lambda: (90, 3))
    assert auto.run_task("prekickoff", lambda: pytest.fail("No ejecutar")) == 0
    assert auto.read_state("prekickoff")["status"] == "diferida"
    assert auto.run_task("prekickoff", lambda: 0, urgent=lambda: True) == 0
    assert auto.read_state("prekickoff")["status"] == "completa"


def test_unhandled_work_failure_is_persisted():
    def work():
        raise RuntimeError("fallo")

    with pytest.raises(RuntimeError):
        auto.run_task("daily", work)
    assert auto.read_state("daily")["status"] == "falló"


def test_incremental_retries_failure_and_missing_artifact(tmp_path):
    calls = []
    assert auto.incremental("ml", "r1", lambda: calls.append(1))
    assert not auto.incremental("ml", "r1", lambda: calls.append(2))
    assert auto.incremental("ml", "r2", lambda: calls.append(3))
    assert auto.incremental("ml", "r2", lambda: calls.append(4), required=(tmp_path / "missing",))
    with pytest.raises(RuntimeError):
        auto.incremental("ml", "r3", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert auto.read_state("incremental")["ml"] == "r2"
    assert calls == [1, 3, 4]


def test_semantic_revision_ignores_live_and_timestamp_but_detects_correction():
    conn = connect(":memory:")
    conn.execute("INSERT INTO competitions VALUES (1, 'TEST', 'Prueba', 'Chile', 'league')")
    conn.executemany("INSERT INTO teams VALUES (?, ?, 'Chile')", [(1, "A"), (2, "B")])
    conn.execute("INSERT INTO matches (id,competition_id,season,kickoff_utc,home_team_id,away_team_id,status,"
                 "home_goals,away_goals,created_at,updated_at) VALUES "
                 "(1,1,'2026','2026-11-09T00:00:00Z',1,2,'finished',1,0,'a','a')")
    before = auto.data_revision(conn)
    conn.execute("UPDATE matches SET updated_at='b'")
    conn.execute("INSERT INTO live_scores VALUES (1,2,0,'45','b')")
    assert auto.data_revision(conn) == before
    conn.execute("UPDATE matches SET home_goals=2")
    assert auto.data_revision(conn) != before
    rows = [(1, 1, "shots", 4, "test", "a"), (1, 2, "shots", 6, "test", "a")]
    conn.executemany("INSERT INTO team_match_stats VALUES (?,?,?,?,?,?)", rows)
    stats_revision = auto.data_revision(conn)
    conn.executemany("INSERT OR REPLACE INTO team_match_stats VALUES (?,?,?,?,?,?)", reversed(rows))
    assert auto.data_revision(conn) == stats_revision
    conn.execute("UPDATE team_match_stats SET value=7 WHERE team_id=2")
    assert auto.data_revision(conn) != stats_revision
