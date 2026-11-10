"""Integración ligera, CLI sin escritura y publicación de caché simulada."""

from pathlib import Path

import pytest
import requests
import test_odds_scout_cycle as cycle
from scripts.odds_scout import main

from footy_agents import odds_scout


@pytest.fixture
def db(tmp_path):
    yield from cycle.db.__wrapped__(tmp_path)


def test_cli_dry_run_changes_no_rows(db, capsys, tmp_path, monkeypatch):
    class Clock(odds_scout.datetime):
        @classmethod
        def now(cls, tz=None):
            return cycle.NOW

    monkeypatch.setattr(odds_scout, "datetime", Clock)
    before = list(db.iterdump())
    path = Path(db.execute("PRAGMA database_list").fetchone()[2])
    output = tmp_path / "dry.json"
    assert main(["--dry-run", "--database", str(path), "--output", str(output)]) == 0
    assert list(db.iterdump()) == before and output.exists()
    text = capsys.readouterr().out
    assert "PERCIBIR" in text and "DECIDIR" in text and "ACTUAR: 0" in text


def test_public_cache_hook_only_for_real_database(db, monkeypatch):
    from footy.web import service
    from footy.web.services import snapshots

    events = []
    monkeypatch.setattr(snapshots, "advance_revision", lambda: events.append("revision"))
    monkeypatch.setattr(service, "clear_caches", lambda: events.append("clear"))
    monkeypatch.setattr(requests, "post", lambda *a, **kw: events.append("post"))
    odds_scout.publish_changes(db)
    assert not events
    path = Path(db.execute("PRAGMA database_list").fetchone()[2])
    monkeypatch.setattr(odds_scout.config, "path", lambda _: path)
    odds_scout.publish_changes(db)
    assert events == ["revision", "clear", "post"]


def test_safely_contains_database_error(monkeypatch):
    import sqlite3

    monkeypatch.setattr(odds_scout, "connect", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("ocupado")))
    odds_scout.run_safely()


def test_daily_lazy_hook(monkeypatch):
    from scripts import daily

    calls = []
    monkeypatch.setattr(odds_scout, "run_safely", lambda: calls.append("scout"))
    daily.run_odds_scout()
    assert calls == ["scout"]


def test_redirected_console_is_utf8_even_with_windows_encoding(db):
    import os
    import subprocess
    import sys

    path = db.execute("PRAGMA database_list").fetchone()[2]
    environment = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    script = Path(__file__).parents[2] / "scripts" / "odds_scout.py"
    result = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--database", path], capture_output=True, env=environment, check=True
    )
    text = result.stdout.decode("utf-8")
    assert "simulación=True" in text and "\ufffd" not in text
