"""Cliente de API-Football sin red: sesión falsa que devuelve respuestas programadas."""

import pytest
import requests

from footy.db import repository as repo
from footy.db.connection import connect
from footy.ingest import api_football as af
from footy.ingest.collect import run_daily

STATUS = {"response": {"requests": {"current": 10, "limit_day": 100}}}
QUOTA = {"errors": {"requests": "You have reached the request limit for the day"}, "results": 0, "response": []}


class FakeResponse:
    def __init__(self, data=None, status=200, remaining=None, text=False):
        self._data, self.status_code, self._text = data, status, text
        self.headers = {} if remaining is None else {"x-ratelimit-requests-remaining": str(remaining)}

    def json(self):
        if self._text:
            raise ValueError("no es JSON")
        return self._data


class FakeSession:
    """Devuelve /status y luego, en orden, cada elemento de `script` (respuesta o excepción)."""

    def __init__(self, *script, status=STATUS):
        self.script, self.status, self.calls = list(script), status, []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        if url.endswith("/status"):
            if isinstance(self.status, Exception):
                raise self.status
            return FakeResponse(self.status)
        self.calls.append((url.rsplit("/", 1)[1], params))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(af.config, "path", lambda name: tmp_path / name)
    monkeypatch.setattr(af.time, "sleep", lambda s: None)
    c = connect(":memory:")
    repo.sync_competitions(c)
    return c


def client(conn, *script, **kw):
    c = af.ApiFootball(conn, key="x", session=FakeSession(*script, **kw))
    c.min_interval = 0
    return c


def test_session_retries_transient_errors_with_backoff():
    retry = af.make_session("x").get_adapter(af.BASE_URL).max_retries
    assert retry.total == 3 and retry.backoff_factor == 1
    assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
    assert "GET" in retry.allowed_methods


def test_quota_exhausted_stops_without_more_requests(conn):
    c = client(conn, FakeResponse(QUOTA))
    with pytest.raises(af.BudgetExhausted):
        c.get("odds", fixture=1)
    assert c.remaining == 0
    with pytest.raises(af.BudgetExhausted):                       # no se vuelve a llamar a la API
        c.get("odds", fixture=2)
    assert len(c.session.calls) == 1
    assert conn.execute("SELECT COUNT(*) FROM api_requests").fetchone()[0] == 1   # queda registrada


def test_run_daily_stops_cleanly_when_quota_runs_out(conn, caplog):
    c = client(conn, FakeResponse({"errors": [], "results": 0, "response": []}, remaining=80), FakeResponse(QUOTA))
    with caplog.at_level("WARNING"):
        summary = run_daily(conn, c)
    assert summary["stopped"] == "presupuesto" and summary["end_remaining"] == 0
    assert "presupuesto agotado" in caplog.text and "Traceback" not in caplog.text
    assert len(c.session.calls) == 2                              # ayer y hoy; mañana ya no se pide


def test_network_failure_and_html_502_stop_collection(conn):
    c = client(conn, requests.ConnectionError("sin red"))
    with pytest.raises(af.ApiUnavailable):
        c.get("fixtures", date="2026-10-09")
    c = client(conn, FakeResponse(status=502, text=True))
    with pytest.raises(af.ApiUnavailable, match="502"):
        c.get("fixtures", date="2026-10-09")
    summary = run_daily(conn, client(conn, requests.Timeout("timeout")))
    assert summary["stopped"] == "api_no_disponible"


def test_status_unavailable_skips_collection_without_raising(conn):
    c = client(conn, status=requests.ConnectionError("sin red"))
    assert c.remaining == 0 and c.unavailable
    assert run_daily(conn, c)["stopped"] == "api_no_disponible" and c.session.calls == []


def test_per_minute_rate_limit_waits_and_retries_once(conn):
    ok = {"errors": [], "results": 1, "response": [{"x": 1}]}
    c = client(conn, FakeResponse({"errors": {"rateLimit": "Too many requests"}, "response": []}), FakeResponse(ok))
    assert c.get("odds", fixture=1)["response"] == [{"x": 1}]
    assert len(c.session.calls) == 2


def test_other_api_errors_skip_only_that_request(conn):
    c = client(conn, FakeResponse({"errors": {"fixture": "invalid"}, "response": []}))
    with pytest.raises(af.ApiError):
        c.get("odds", fixture=1)
    assert c.remaining > c.reserve


def test_collect_odds_keeps_low_budget_for_priority_one_matches_soon(conn, caplog, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from footy.ingest import collect

    now = datetime.now(timezone.utc)
    comps = af.config.settings()["competitions"]
    p1 = next(c for c, v in comps.items() if v.get("collect_odds") and v.get("odds_priority", 5) == 1)
    p2 = next(c for c, v in comps.items() if v.get("collect_odds") and v.get("odds_priority", 5) > 1)
    games = {}
    for i, (code, hours) in enumerate([(p1, 3), (p2, 3), (p1, 30)]):
        h = repo.resolve_team(conn, "x", f"H{i}", f"Local {i}", "Chile")     # equipos distintos: no se enlazan
        a = repo.resolve_team(conn, "x", f"A{i}", f"Visita {i}", "Chile")
        mid = repo.upsert_match(conn, source=af.SOURCE, source_match_id=str(100 + i),
                                competition_id=repo.competition_id(conn, code), season="2026",
                                kickoff_utc=repo.to_iso(now + timedelta(hours=hours)),
                                home_team_id=h, away_team_id=a, status="scheduled")
        games[100 + i] = mid
    c = client(conn, *[FakeResponse({"errors": [], "results": 0, "response": []}) for _ in range(3)])
    c.remaining = collect.LOW_BUDGET - 1                     # presupuesto bajo
    with caplog.at_level("INFO"):
        collect.collect_odds(c, conn, horizon_hours=36)
    assert [p["fixture"] for _, p in c.session.calls] == ["100"]   # solo prioridad 1 y dentro de 12 h
    assert "Omitiendo cuotas de ligas secundarias" in caplog.text
    c2 = client(conn, *[FakeResponse({"errors": [], "results": 0, "response": []}) for _ in range(3)])
    collect.collect_odds(c2, conn, horizon_hours=36)            # con presupuesto normal se piden todos
    assert sorted(p["fixture"] for _, p in c2.session.calls) == ["100", "101", "102"]
