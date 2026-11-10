"""Descarga cacheada, 304 y continuidad sin red; nunca inicia descargas desde la web."""

import json
from types import SimpleNamespace

import pytest
import requests

from footy.ingest import international as source


@pytest.fixture
def target(tmp_path, monkeypatch):
    path = tmp_path / "results.csv"
    monkeypatch.setattr(source, "RAW", path)
    return path


class Response:
    status_code = 200
    content = b"csv-publico"
    headers = {"ETag": '"v1"', "Last-Modified": "date"}

    def raise_for_status(self):
        pass


def test_cache_starts_once_and_304_does_not_change_csv(target, monkeypatch):
    calls = []
    response = Response()

    def get(*a, **kw):
        calls.append(kw)
        return response

    monkeypatch.setattr(source.requests, "get", get)
    assert source.refresh_results() == target
    stamp = target.stat().st_mtime_ns
    assert source.refresh_results() == target and len(calls) == 1
    response.status_code = 304
    assert source.refresh_results(force=True) == target
    assert target.stat().st_mtime_ns == stamp
    assert calls[-1]["headers"] == {"If-None-Match": '"v1"', "If-Modified-Since": "date"}


def test_identical_body_keeps_timestamp_and_changed_body_replaces(target, monkeypatch):
    response = Response()
    monkeypatch.setattr(source.requests, "get", lambda *a, **kw: response)
    source.refresh_results()
    stamp = target.stat().st_mtime_ns
    source.refresh_results(force=True)
    assert target.stat().st_mtime_ns == stamp
    response.content = b"nueva-version"
    source.refresh_results(force=True)
    assert target.read_bytes() == b"nueva-version"


def test_network_failure_uses_local_but_missing_file_fails(target, monkeypatch):
    def down(*a, **kw):
        raise requests.ConnectionError()

    monkeypatch.setattr(source.requests, "get", down)
    with pytest.raises(requests.ConnectionError):
        source.refresh_results()
    target.write_text("copia local")
    assert source.refresh_results(force=True) == target


def test_unexpected_304_without_file_fails_and_bad_metadata_recovers(target, monkeypatch):
    response = Response()
    response.status_code = 304
    monkeypatch.setattr(source.requests, "get", lambda *a, **kw: response)
    with pytest.raises(ValueError, match="sin CSV"):
        source.refresh_results()
    target.with_suffix(".json").write_text("[]")
    response.status_code = 200
    source.refresh_results()
    assert isinstance(json.loads(target.with_suffix(".json").read_text()), dict)


def test_failed_poisson_fit_is_not_published(monkeypatch):
    from test_international import match

    from footy.models import international

    monkeypatch.setattr(international, "minimize", lambda *a, **kw: SimpleNamespace(success=False))
    with pytest.raises(ValueError, match="convergió"):
        international.fit([match()], source.TeamNames())
