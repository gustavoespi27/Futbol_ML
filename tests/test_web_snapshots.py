"""Equivalencia exacta del cálculo de respaldo y del precalculado, sin modelos reales."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

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


@pytest.mark.parametrize("change", ["expired", "signature", "corrupt", "kickoff"])
def test_invalid_snapshot_uses_fallback(cache, monkeypatch, change):
    snapshots.write(5, [], "v1")
    path = cache / "5.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    if change == "expired":
        saved["created"] = time.time() - snapshots.MAX_AGE - 1
    elif change == "signature":
        saved["signature"] = "old"
    elif change == "kickoff":
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
