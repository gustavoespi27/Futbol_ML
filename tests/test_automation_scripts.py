"""Salidas ligeras y clasificación temporal de las tareas."""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from scripts import daily, prekickoff

from footy.db.connection import connect
from footy.web.services import snapshots
from footy_agents import automation


def test_no_matches_exits_without_heavy_imports(tmp_path):
    code = f"""
import json,sys,time
from pathlib import Path
started=time.perf_counter()
from footy import config
config.PROJECT_ROOT=Path({str(tmp_path)!r})
config.path=lambda key: config.PROJECT_ROOT/'empty.sqlite'
from scripts import prekickoff
result=prekickoff.main()
print(json.dumps({{'result':result,'seconds':time.perf_counter()-started,
                 'heavy':[m for m in ('numpy','pandas','sklearn') if m in sys.modules]}}))
"""
    result = json.loads(subprocess.check_output([sys.executable, "-c", code], text=True))
    assert result["result"] == 0 and result["heavy"] == []


def test_urgency_uses_actual_kickoff_window():
    conn = connect(":memory:")
    conn.execute("INSERT INTO competitions VALUES (1,'TEST','Prueba','Chile','league')")
    conn.executemany("INSERT INTO teams VALUES (?,?,'Chile')", [(1, "A"), (2, "B")])
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("INSERT INTO matches (competition_id,season,kickoff_utc,home_team_id,away_team_id,status,"
                 "created_at,updated_at) VALUES (1,'2026',?,1,2,'scheduled','a','a')", (kickoff,))
    assert prekickoff.starts_within(conn, 12)
    assert not prekickoff.starts_within(conn, 1.5)
    kickoff = (datetime.now(timezone.utc) + timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("UPDATE matches SET kickoff_utc=?", (kickoff,))
    assert prekickoff.starts_within(conn, 1.5)


def test_daily_models_skip_unchanged_and_missing_artifact_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(automation, "directory", lambda: tmp_path)
    monkeypatch.setattr(snapshots, "advance_revision", lambda: None)
    conn = connect(":memory:")
    paths = [tmp_path / name for name in ("calibration", "cross", "ml")]
    for path in paths:
        path.write_text("modelo")
    calls = []
    calibration = SimpleNamespace(PATH=paths[0], update=lambda conn: calls.append("calibration"))
    cross = SimpleNamespace(PATH=paths[1], fit=lambda conn: calls.append("cross"))
    ml = SimpleNamespace(CACHE=paths[2], upcoming=lambda **kw: calls.append("ml") or [])

    def save(model):
        paths[1].write_text("reconstruido")
        return 0

    monkeypatch.setattr(daily, "_save_cross", save)
    daily.update_models(conn, calibration, cross, ml)
    automation.write_state("data", {"revision": automation.data_revision(conn)})
    daily.update_models(conn, calibration, cross, ml)
    assert calls == ["calibration", "cross", "ml"]
    paths[1].unlink()
    daily.update_models(conn, calibration, cross, ml)
    assert calls == ["calibration", "cross", "ml", "cross"]
