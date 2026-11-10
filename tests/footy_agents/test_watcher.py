"""Vigía sin LLM: condiciones, evidencia, deduplicación y límites de escritura."""

import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from footy_agents import watcher, watches
from footy_agents.grounding import verify_numbers
from footy_agents.schemas import ToolCallRecord
from footy_agents.watch_schemas import WatchArgs

NOW = datetime(2026, 11, 9, 20, tzinfo=timezone.utc)


def match(id_=181043, hours=6, pin=True, value=False):
    return {
        "ref": f"m:{id_}",
        "home": "Colombia",
        "away": "Chile",
        "source": "mercado" if pin else "modelo",
        "kickoff": (NOW + timedelta(hours=hours)).isoformat(),
        "p_official": [0.6, 0.25, 0.15],
        "odds_1x2": {"Pinnacle": [1.5, 4, 6]} if pin else {},
        "pro": [{"key": "1", "edge": 0.08, "bet": value, "pinnacle": 1.5}] if pin else [],
    }


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    # alerts() oculta avisos de partidos ya iniciados: el reloj de lectura debe coincidir con NOW.
    monkeypatch.setattr(watches, "utc_now", lambda: NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "watch.sqlite")
    conn.executescript(
        "CREATE TABLE teams(id INTEGER PRIMARY KEY,name TEXT);"
        "INSERT INTO teams VALUES(1,'Chile'),(2,'Colombia');"
        "CREATE TABLE matches(id INTEGER PRIMARY KEY);"
        "INSERT INTO matches VALUES(181043),(2);"
        "CREATE TABLE pro_bets(id INTEGER); INSERT INTO pro_bets VALUES(7);"
        "CREATE TABLE daily_picks(id INTEGER); INSERT INTO daily_picks VALUES(8);"
    )
    yield conn
    conn.close()


@pytest.mark.parametrize(
    "condition",
    ["kickoff_soon", "pinnacle_available", "value_appears", "line_move", "probability_shift", "coverage_lost"],
)
def test_every_watch_condition_and_idempotence(db, condition):
    before = match(pin=condition != "pinnacle_available")
    watcher.run(db, [before], NOW)
    created = watches.create_watch(db, "default", WatchArgs(match_id=181043, condition=condition))
    assert watches.create_watch(db, "default", WatchArgs(match_id=181043, condition=condition))["id"] == created["id"]
    assert (
        watches.create_watch(db, "default", WatchArgs(match_id=181043, condition=condition))["note"]
        == "ya estaba vigilando"
    )
    after = match()
    if condition == "value_appears":
        after["pro"][0]["bet"] = True
    if condition == "line_move":
        after["odds_1x2"]["Pinnacle"][0] *= 1.05
    if condition == "probability_shift":
        after["p_official"] = [0.63, 0.22, 0.15]
    if condition == "coverage_lost":
        after = match(pin=False)
    result = watcher.run(db, [after], NOW)
    own = [a for a in watches.alerts(db, "default") if a.watch_id == created["id"]]
    assert len(own) == 1 and own[0].kind == condition
    record = ToolCallRecord(tool_name="facts", arguments={}, result=own[0].facts, success=True, execution_time_ms=0)
    assert verify_numbers(own[0].text, [record]).verified
    assert any(d.selected and d.watch_id == created["id"] for d in result.decisions)
    assert watches.list_watches(db, "default")[0].status == "fulfilled"
    count = len(watches.alerts(db, "default"))
    assert watcher.run(db, [after], NOW).actions == 0
    assert len(watches.alerts(db, "default")) == count
    assert db.execute("SELECT * FROM pro_bets").fetchall() == [(7,)]
    assert db.execute("SELECT * FROM daily_picks").fetchall() == [(8,)]


@pytest.mark.parametrize(
    "condition,kwargs,reason",
    [
        ("kickoff_soon", {"hours": 25}, "24"),
        ("kickoff_soon", {"hours": -1}, "iniciado"),
        ("pinnacle_available", {"pin": False}, "Sin Pinnacle"),
        ("value_appears", {}, "Sin selección"),
        ("line_move", {"pin": False}, "Faltan"),
        ("probability_shift", {}, "Sin cambio"),
        ("coverage_lost", {}, "Sin cambio"),
    ],
)
def test_discard_reasons(db, condition, kwargs, reason):
    watcher.run(db, [match()], NOW)
    watches.create_watch(db, "default", WatchArgs(match_id=181043, condition=condition))
    report = watcher.run(db, [match(**kwargs)], NOW)
    own = [d for d in report.decisions if d.watch_id]
    assert len(own) == 1 and not own[0].selected and reason in own[0].reason


def test_global_rules_and_first_snapshot_do_not_invent_transitions(db):
    row = match(value=True)
    assert watcher.run(db, [row], NOW).actions == 0
    after = match(pin=False)
    report = watcher.run(db, [after], NOW)
    assert {d.kind for d in report.decisions if d.selected} == {"value_disappears", "coverage_lost"}
    assert watcher.run(db, [after], NOW).actions == 0
    report = watcher.run(db, [row], NOW)
    assert {d.kind for d in report.decisions if d.selected} == {"value_appears"}
    assert all(d.reason for d in report.decisions)
    assert watches.recent_logs(db)[0].actions == 1
    alert = watches.alerts(db, "default", unread=True)[0]
    assert watches.mark_read(db, "otro", alert.id) is False
    assert watches.mark_read(db, "default", alert.id) is True
    assert alert.id not in [a.id for a in watches.alerts(db, "default", unread=True)]


def test_team_watch_priority_missing_target_and_user_isolation(db):
    watches.create_watch(db, "u", WatchArgs(team="Chile", condition="kickoff_soon"))
    watches.create_watch(db, "otro", WatchArgs(match_id=2, condition="pinnacle_available"))
    report = watcher.run(db, [match(2, hours=2), match(hours=1)], NOW)
    team_alerts = watches.alerts(db, "u")
    assert len(team_alerts) == 1 and team_alerts[0].match_id == 181043 and team_alerts[0].priority >= 300
    assert any("mayor prioridad" in d.reason for d in report.decisions)
    assert len(watches.alerts(db, "otro")) == 1
    assert not watches.alerts(db, "ajeno")
    assert all(d.user_id == "u" for d in watches.recent_logs(db, user_id="u")[0].decisions)
    watches.create_watch(db, "u", WatchArgs(match_id=181043, condition="pinnacle_available"))
    missing = watcher.run(db, [], NOW)
    assert any("sin partido" in d.reason for d in missing.decisions)


def test_cancel_targets_and_foreign_ids(db):
    with pytest.raises(ValueError, match="match_id"):
        watches.create_watch(db, "u", WatchArgs(match_id=999, condition="kickoff_soon"))
    with pytest.raises(ValueError, match="equipo"):
        watches.create_watch(db, "u", WatchArgs(team="Inventado", condition="kickoff_soon"))
    id_ = watches.create_watch(db, "u", WatchArgs(team="Chile", condition="kickoff_soon"))["id"]
    with pytest.raises(ValueError, match="usuario"):
        watches.cancel_watch(db, "otro", id_)
    assert watches.cancel_watch(db, "u", id_)["note"] == "Vigilancia cancelada"
    assert watches.cancel_watch(db, "u", id_)["note"] == "Ya estaba inactiva"
    assert watches.create_watch(db, "u", WatchArgs(team="Chile", condition="kickoff_soon"))["id"] != id_


def test_threshold_boundaries_and_missing_values():
    row = watcher.perceive([match()])[181043]
    current = deepcopy(row)
    current["pinnacle"][0] *= 1.049
    assert not watcher.evaluate("line_move", current, row, NOW)[0]
    current["pinnacle"][0] = row["pinnacle"][0] * 1.05
    assert watcher.evaluate("line_move", current, row, NOW)[0]
    current["p_official"] = None
    assert "Faltan" in watcher.evaluate("probability_shift", current, row, NOW)[1]
    distant = watcher.perceive([match(pin=False, hours=12)])[181043]
    assert "fuera" in watcher.evaluate("coverage_lost", distant, row, NOW, global_rule=True)[1]
    assert not watcher.evaluate("line_move", row, None, NOW)[0]
    with pytest.raises(ValueError, match="desconocida"):
        watcher.evaluate("invalid", row, row, NOW)
    assert watcher._valid([True, 0.2, 0.3]) is None
    assert watcher._valid([float("nan"), 0.2, 0.3]) is None
    assert watcher._valid([1, 2]) is None
    no_raw = match()
    no_raw["odds_1x2"] = {}
    no_raw["pro"] = [{"key": k, "pinnacle": p} for k, p in zip(("1", "X", "2"), (1.5, 4, 6))]
    assert watcher.perceive([no_raw])[181043]["has_pinnacle"]
    assert watcher.perceive([{"ref": "sim:1"}]) == {}


def test_templates_verify_and_reject_extra_numbers(monkeypatch):
    facts = watcher.alert_facts("line_move", watcher.perceive([match()])[181043], {"pinnacle": [1, 4, 6]}, NOW)
    assert "50 %" in watcher.alert_text(facts)
    monkeypatch.setitem(watcher.LABELS, "line_move", "se movió 999999 %")
    with pytest.raises(ValueError, match="fuera de facts"):
        watcher.alert_text(facts)


def test_wrapper_never_breaks_pipeline(db, monkeypatch, caplog):
    def unavailable():
        raise sqlite3.OperationalError("fallo simulado")

    monkeypatch.setattr(watcher, "connect", unavailable)
    watcher.run_safely()
    assert "pipeline continúa" in caplog.text


def test_only_agent_tables_are_written(db):
    watches.init_tables(db)
    from footy_agents.preferences.repo import init_preferences_table

    init_preferences_table(db)

    def authorizer(action, table, column, database, trigger):
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
            if not table.startswith("agent_") and table != "sqlite_master":
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.set_authorizer(authorizer)
    watches.create_watch(db, "default", WatchArgs(match_id=181043, condition="pinnacle_available"))
    assert watcher.run(db, [match()], NOW).actions == 1
    assert json.loads(db.execute("SELECT facts FROM agent_alerts").fetchone()[0])["has_pinnacle"]


def test_no_llm_is_created_or_started(db, monkeypatch):
    from footy_agents.llm import OpenAICompatibleClient
    from footy_agents.ollama_runtime import runtime

    def forbidden(*args, **kwargs):
        pytest.fail("El vigía nunca debe iniciar ni usar un LLM")

    monkeypatch.setattr(OpenAICompatibleClient, "from_settings", forbidden)
    monkeypatch.setattr(runtime, "ensure_running", forbidden)
    watches.create_watch(db, "default", WatchArgs(match_id=181043, condition="pinnacle_available"))
    assert watcher.run(db, [match()], NOW).actions == 1


def test_existing_watch_log_migrates_without_data_loss(db):
    db.execute(
        "CREATE TABLE agent_watch_log(id INTEGER PRIMARY KEY,run_at TEXT,perceived INTEGER,decisions TEXT,"
        "actions INTEGER,elapsed_ms REAL)"
    )
    db.execute("INSERT INTO agent_watch_log VALUES(9,'2026-11-09T00:00:00Z',40,'[]',0,1.5)")
    db.commit()
    watches.init_tables(db)
    watches.init_tables(db)
    assert watches.recent_logs(db)[0].id == 9 and watches.recent_logs(db)[0].perception == {}


def test_simultaneous_runs_do_not_duplicate_alert(db):
    from concurrent.futures import ThreadPoolExecutor

    path = db.execute("PRAGMA database_list").fetchone()[2]
    watches.create_watch(db, "default", WatchArgs(match_id=181043, condition="pinnacle_available"))

    def worker():
        with sqlite3.connect(path) as conn:
            return watcher.run(conn, [match()], NOW).actions

    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda _: worker(), range(2)))
    assert sum(counts) == 1 and len(watches.alerts(db, "default")) == 1
