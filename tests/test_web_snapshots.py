"""Equivalencia exacta del cálculo de respaldo y del precalculado, sin modelos reales."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from footy.db.connection import connect
from footy.web.services import context, snapshots
from footy.web.services.common import to_json


@pytest.fixture
def cache(tmp_path, monkeypatch):
    context.clear_caches()
    monkeypatch.setattr(snapshots, "DIRECTORY", tmp_path)
    monkeypatch.setattr(snapshots, "signature", lambda: "v1")
    yield tmp_path
    context.clear_caches()


def test_precalculated_identical_to_inline_and_shared_across_process_cache(cache, monkeypatch):
    expected = [{"ref": "m:1", "kickoff": "2099-01-01T00:00:00Z", "p_official": [0.51, 0.29, 0.2],
                 "stats": {"x": 1.2345678901}, "optional": None}]
    calls = []
    monkeypatch.setattr(context, "_upcoming", lambda days: calls.append(days) or expected)
    inline = context.upcoming(refresh=True)
    context.clear_caches()
    saved = context.upcoming()
    assert to_json(inline) == saved == expected
    assert calls == [context.HORIZON_DAYS]


def test_concurrent_cold_requests_calculate_once(cache, monkeypatch):
    calls = []

    def compute(days):
        calls.append(days)
        time.sleep(0.01)
        return []
    monkeypatch.setattr(context, "_upcoming", compute)
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(lambda _: context.upcoming(), range(4))) == [[], [], [], []]
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["expired", "signature", "corrupt", "midnight"])
def test_invalid_snapshot_uses_fallback(cache, monkeypatch, change):
    snapshots.write(5, [], "v1")
    path = cache / "5.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    if change == "expired":
        saved["created"] = time.time() - snapshots.MAX_AGE - 1
    elif change == "signature":
        saved["signature"] = "old"
    elif change == "midnight":
        saved["expires"] = time.time() - 1
    path.write_text("bad" if change == "corrupt" else json.dumps(saved), encoding="utf-8")
    calls = []
    monkeypatch.setattr(context, "_upcoming", lambda days: calls.append(days) or [])
    assert context.upcoming() == [] and calls == [5]


def test_changed_inputs_invalidate_memory_and_do_not_publish_mixed_snapshot(cache, monkeypatch):
    monkeypatch.setattr(context, "_upcoming", lambda days: [])
    context.upcoming()
    monkeypatch.setattr(snapshots, "signature", lambda: "v2")
    calls = []
    monkeypatch.setattr(context, "_upcoming", lambda days: calls.append(days) or [])
    context.upcoming()
    assert calls == [5]
    snapshots.write(7, [], "v1")
    assert not (cache / "7.json").exists()


@pytest.mark.parametrize("stage", ["mkdir", "write", "replace"])
def test_storage_failure_does_not_break_inline_response(cache, monkeypatch, stage):
    monkeypatch.setattr(context, "_upcoming", lambda days: [])

    def denied(*args, **kwargs):
        raise PermissionError("almacenamiento no escribible")
    if stage == "mkdir":
        monkeypatch.setattr(type(cache), "mkdir", denied)
    elif stage == "write":
        monkeypatch.setattr(snapshots.tempfile, "NamedTemporaryFile", denied)
    else:
        monkeypatch.setattr(snapshots.os, "replace", denied)
    assert context.upcoming() == []
    assert list(cache.iterdir()) == []


def test_live_scores_do_not_invalidate_signature_or_recalculate(tmp_path, monkeypatch):
    context.clear_caches()
    monkeypatch.setattr(snapshots, "DIRECTORY", tmp_path / "upcoming")
    original_path = snapshots.config.path
    monkeypatch.setattr(snapshots.config, "path", lambda key: tmp_path / "football.sqlite" if key == "database"
                        else original_path(key))
    conn = connect(tmp_path / "football.sqlite")
    conn.executescript("""
        INSERT INTO competitions VALUES (1,'TEST','Prueba',NULL,'league');
        INSERT INTO teams VALUES (1,'A',NULL),(2,'B',NULL);
        INSERT INTO matches(id,competition_id,season,kickoff_utc,home_team_id,away_team_id,status,created_at,updated_at)
        VALUES (1,1,'2099','2099-01-01T00:00:00Z',1,2,'scheduled','2026-01-01','2026-01-01');
    """)
    snapshots.advance_revision()
    baseline = snapshots.signature()
    calls = []
    expected = [{"ref": "m:1", "kickoff": "2099-01-01T00:00:00Z"}]
    monkeypatch.setattr(context, "_upcoming", lambda days: calls.append(days) or expected)
    context._predictors["sentinel"] = (time.time(), object())
    context._contexts["sentinel"] = (time.time(), {})
    predictor = context._predictors["sentinel"]
    cached_context = context._contexts["sentinel"]
    assert context.upcoming() == expected
    for score in range(3):
        conn.execute("INSERT OR REPLACE INTO live_scores VALUES (1,?,0,'45',?)", (score, str(score)))
        conn.commit()
        assert snapshots.signature() == baseline
        assert context.upcoming() == expected
    # También tras vencer la memoria se reutiliza el disco, sin invocar el cálculo.
    context._upcoming_cache[5] = (0, expected)
    assert context.upcoming() == expected and calls == [5]
    assert context._predictors["sentinel"] is predictor
    assert context._contexts["sentinel"] is cached_context
    snapshots.advance_revision()
    assert snapshots.signature() != baseline
    assert context.upcoming() == expected and calls == [5, 5]
    conn.close()
    context.clear_caches()


def test_kickoff_filters_memory_and_disk_without_recalculation(cache, monkeypatch):
    now = time.time()
    from datetime import datetime, timezone

    matches = [{"ref": f"m:{i}", "kickoff": datetime.fromtimestamp(now + seconds, timezone.utc).isoformat()}
               for i, seconds in enumerate((10, 1000))]
    calls = []
    monkeypatch.setattr(context, "_upcoming", lambda days: calls.append(days) or matches)
    assert context.upcoming() == matches
    monkeypatch.setattr(time, "time", lambda: now + 20)
    assert context.upcoming() == matches[1:]
    context._upcoming_cache.clear()
    assert context.upcoming() == matches[1:] and calls == [5]


def test_model_files_invalidate_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "DIRECTORY", tmp_path)
    monkeypatch.setattr(snapshots.config, "PROJECT_ROOT", tmp_path)
    baseline = snapshots.signature()
    model = tmp_path / "artifacts/ml/model.joblib"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"modelo actualizado")
    assert snapshots.signature() != baseline
