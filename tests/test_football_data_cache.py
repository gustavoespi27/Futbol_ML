"""Caché HTTP confirmada solo tras ingesta; 304 y 200 idéntico no vuelven a parsear."""

import pytest

from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest import football_data as fd

CSV = ("Country,League,Season,Date,Time,Home,Away,HG,AG\n"
       "Argentina,Liga Profesional,2026,15/01/2026,20:00,A,B,0,1\n")


class Response:
    def __init__(self, status=200, text=CSV):
        self.status_code = status
        self.content = text.encode()
        self.headers = {"ETag": '"version-1"', "Last-Modified": "Mon, 09 Nov 2026 00:00:00 GMT"}

    def raise_for_status(self):
        pass


@pytest.fixture
def setup(tmp_path, monkeypatch):
    database = tmp_path / "data.sqlite"
    leagues = fd.leagues()
    conn = connect(database)
    repo.sync_competitions(conn)
    monkeypatch.setattr(fd, "leagues", lambda: leagues)
    monkeypatch.setattr(fd.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fd.config, "path", lambda key: database if key == "database" else tmp_path / key)
    monkeypatch.setattr(fd, "_save_raw", lambda *a: None)
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs)
        return Response(200 if len(calls) == 1 else 304)

    monkeypatch.setattr(fd.requests, "get", get)
    yield conn, calls
    conn.close()


def test_304_avoids_parse_only_after_successful_store(setup, monkeypatch):
    conn, calls = setup
    first = fd.download("ARG", only_changed=True)
    # Sin confirmar en DB: debe recuperar el CSV cacheado y reintentar la ingesta.
    assert not fd.download("ARG", only_changed=True).empty
    fd.store(conn, first)
    monkeypatch.setattr(fd, "parse_extra", lambda *a: pytest.fail("No reparsear CSV sin cambios"))
    assert fd.download("ARG", only_changed=True).empty
    assert calls[-1]["headers"] == {"If-None-Match": '"version-1"',
                                    "If-Modified-Since": "Mon, 09 Nov 2026 00:00:00 GMT"}
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


def test_identical_200_avoids_parse_but_changed_content_is_ingested(setup, monkeypatch):
    conn, _ = setup
    fd.store(conn, fd.download("ARG", only_changed=True))
    monkeypatch.setattr(fd.requests, "get", lambda *a, **kw: Response())
    assert fd.download("ARG", only_changed=True).empty
    monkeypatch.setattr(fd.requests, "get", lambda *a, **kw: Response(text=CSV.replace(",0,1", ",2,1")))
    changed = fd.download("ARG", only_changed=True)
    assert not changed.empty
    fd.store(conn, changed)
    assert conn.execute("SELECT home_goals FROM matches").fetchone()[0] == 2


def test_regular_download_retains_cached_text_for_existing_callers(setup):
    conn, _ = setup
    fd.store(conn, fd.download("ARG", only_changed=True))
    assert not fd.download("ARG").empty


def test_missing_cache_does_not_send_conditional_headers(setup):
    _, calls = setup
    fd.download("ARG", only_changed=True)
    assert calls[0]["headers"] == {}


def test_404_is_empty_without_parsing(setup, monkeypatch):
    monkeypatch.setattr(fd.requests, "get", lambda *a, **kw: Response(404))
    assert fd.download("ARG", only_changed=True).empty


def test_main_cache_retains_confirmation_across_concat(setup, monkeypatch):
    conn, _ = setup
    csv = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE1,15/01/2026,A,B,0,1\n"
    monkeypatch.setattr(fd.requests, "get", lambda *a, **kw: Response(text=csv))
    frame = fd.download("E1", seasons=[2025], only_changed=True)
    assert frame.attrs["http_sources"]
    fd.store(conn, frame)
    monkeypatch.setattr(fd, "parse_main", lambda *a: pytest.fail("No reparsear"))
    assert fd.download("E1", seasons=[2025], only_changed=True).empty
