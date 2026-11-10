"""Avisos fuera del chat: tipos, combinadas entre partidos distintos, expiración, deduplicación y preferencias."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from footy.betting import pro
from footy_agents import notifications, watcher, watches
from footy_agents.grounding import verify_numbers
from footy_agents.preferences import repo
from footy_agents.schemas import DEFAULT_ALERT_TYPES, ToolCallRecord, UserPreferences
from footy_agents.web import router

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
ISO = "%Y-%m-%dT%H:%M:%SZ"


def iso(hours: float) -> str:
    return (NOW + timedelta(hours=hours)).strftime(ISO)


def opt(key, odds, fair, p=0.5, bet=False):
    return {"key": key, "odds": odds, "fair_odds": fair, "p_fair": p, "edge": round(p * odds - 1, 4),
            "book": "Bet365", "bet": bet, "pinnacle": fair}


def row(id_, home, away, hours, options=(), league="E0"):
    return {"ref": f"m:{id_}", "home": home, "away": away, "league": league, "league_name": "Premier League",
            "kickoff": iso(hours), "pro": list(options)}


def single(id_, r, o):
    return {**o, "match": id_, "home": r["home"], "away": r["away"], "kickoff": r["kickoff"]}


A = row(1, "Arsenal", "Chelsea", 5, [opt("1", 2.2, 2.0, p=0.5, bet=True)])          # ventaja 10 %
B = row(2, "Liverpool", "Everton", 8, [opt("1", 2.0, 1.92, p=0.52)])                # ventaja 4 %: cerca
C = row(3, "Colo Colo", "Universidad de Chile", 1.5, [opt("2", 3.0, 3.2, p=0.32)], league="CHL")  # −4 %
D = row(4, "Chile", "Colombia", 30, [])
ROWS = [A, B, C, D]
SUGGESTIONS = {
    "singles": [single(1, A, A["pro"][0])],
    "closest": [{**single(2, B, B["pro"][0]), "min_odds": 2.04}, {**single(3, C, C["pro"][0]), "min_odds": 3.32}],
    "doubles": [],
}


def facts_ok(notice):
    record = ToolCallRecord(tool_name="f", arguments={}, result=notice.facts, success=True, execution_time_ms=0)
    return verify_numbers(notice.text, [record]).verified


@pytest.fixture
def db(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "alerts.sqlite")
    conn.executescript("CREATE TABLE matches(id INTEGER PRIMARY KEY); CREATE TABLE teams(id INTEGER, name TEXT);")
    repo.init_preferences_table(conn)
    watches.init_tables(conn)
    monkeypatch.setattr(watches, "utc_now", lambda: NOW.strftime(ISO))
    yield conn
    conn.close()


def upcoming():
    return notifications._upcoming(ROWS, NOW)


def test_value_and_near_value_from_engine_suggestions():
    notices = notifications.market_notices(upcoming(), SUGGESTIONS)
    by_kind = {}
    for n in notices:
        by_kind.setdefault(n.kind, []).append(n)
    value = by_kind["value_bet"][0]
    assert value.match_ids == (1,) and value.edge == pytest.approx(0.1)
    assert "2,20" in value.text and "2,00" in value.text and "10,0 %" in value.text and "tope 2 %" in value.text
    near = by_kind["near_value"]
    assert [n.match_ids for n in near] == [(2,)]                      # −4 % queda fuera (umbral MIN_EDGE − 3 pp)
    assert "desde cuota 2,04" in near[0].text and "sin monto" in near[0].text
    assert all(facts_ok(n) for n in notices)


def test_combos_only_across_different_matches_with_pinnacle():
    same = row(5, "Real Madrid", "Barcelona", 10, [opt("1", 2.1, 2.05, p=0.49), opt("2", 3.6, 3.5, p=0.29)])
    rows = notifications._upcoming(ROWS + [same], NOW)
    notices = notifications.market_notices(rows, SUGGESTIONS)
    combos = [n for n in notices if n.kind == "near_combo"]
    assert combos and all(len(set(n.match_ids)) == 2 for n in combos)
    assert all(0 <= n.edge < pro.MIN_EDGE for n in combos)
    assert all(4 not in n.match_ids for n in combos)                  # sin Pinnacle no hay pierna
    assert "Informativa, sin monto sugerido" in combos[0].text and all(facts_ok(n) for n in combos)


def test_value_combo_from_engine_doubles():
    b2 = {**B, "pro": [opt("1", 2.3, 2.1, p=0.48, bet=True)]}
    rows = notifications._upcoming([A, b2], NOW)
    legs = [single(1, A, A["pro"][0]), single(2, b2, b2["pro"][0])]
    notices = notifications.market_notices(rows, {"singles": legs, "closest": [], "doubles": [{"legs": legs}]})
    combo = next(n for n in notices if n.kind == "value_combo")
    assert combo.facts["combined_odds"] == pytest.approx(5.06)
    assert combo.edge == pytest.approx(1.1 * (0.48 * 2.3) - 1, abs=1e-3)
    assert not [n for n in notices if n.kind == "near_combo" and n.selection == combo.selection]
    assert facts_ok(combo)


def test_favorite_plays_window_and_reminder():
    notices = notifications.favorite_notices(upcoming(), {"colo colo", "chile"}, set(), NOW)
    assert [(n.match_ids, n.stage) for n in notices] == [((3,), "2h")]      # Chile juega en 30 h: aún no avisa
    assert notices[0].text.startswith("Comienza en menos de dos horas") and facts_ok(notices[0])
    later = notifications.favorite_notices(upcoming(), set(), {"E0"}, NOW)
    assert {n.match_ids for n in later} == {(1,), (2,)} and {n.stage for n in later} == {"24h"}


def test_started_matches_are_ignored():
    started = row(9, "Ajax", "PSV", -1, [opt("1", 3.0, 2.0, p=0.5, bet=True)])
    rows = notifications._upcoming([started], NOW)
    assert rows == {}
    assert notifications.market_notices(rows, {"singles": [single(9, started, started["pro"][0])]}) == []


def test_dedupe_and_realert_only_when_edge_improves(db):
    first = notifications.market_notices(upcoming(), SUGGESTIONS)[0]
    stamp = NOW.strftime(ISO)
    assert notifications.publish(db, "default", first, stamp) == (True, "Aviso nuevo")
    assert notifications.publish(db, "default", first, stamp)[0] is False
    def improved(gain):
        edge = first.edge + gain
        return notifications.Notice(**{**first.__dict__, "edge": edge, "facts": {**first.facts, "edge": edge}})
    better = improved(0.025)
    assert notifications.publish(db, "default", better, stamp) == (True, "Mejoró la ventaja: se vuelve a avisar")
    slightly = improved(0.03)
    assert notifications.publish(db, "default", slightly, stamp)[0] is False


def test_preferences_filter_types_and_favorites():
    notices = notifications.market_notices(upcoming(), SUGGESTIONS)
    conf = {**notifications.DEFAULT_SETTINGS, "types": {"value_bet"}}
    keep, skipped = notifications.for_user(notices, conf)
    assert {n.kind for n in keep} == {"value_bet"} and skipped
    only = {**notifications.DEFAULT_SETTINGS, "only_favorites": True, "teams": {"liverpool"}}
    keep, _ = notifications.for_user(notices, only)
    assert keep and all(2 in n.match_ids for n in keep)


def test_watcher_publishes_alerts_that_expire_at_kickoff(db):
    result = watcher.run(db, ROWS, NOW, suggestions=SUGGESTIONS)
    kinds = {d.kind for d in result.decisions if d.selected}
    assert {"value_bet", "near_value"} <= kinds
    assert "favorite_plays" not in kinds                                # sin favoritos guardados
    listed = watches.alerts(db, "default")
    assert [a.match_id for a in listed] == [1, 2]                       # ordenadas por inicio del partido
    assert all(a.expires_at for a in listed)
    assert watches.alerts(db, "default", now=iso(24)) == []             # tras el inicio dejan de mostrarse
    again = watcher.run(db, ROWS, NOW, suggestions=SUGGESTIONS)
    assert not [d for d in again.decisions if d.selected and d.kind in notifications.ALERT_TYPES]


def test_watcher_uses_saved_preferences(db):
    repo.save_preferences(db, UserPreferences(favorite_teams=["Colo Colo"], alert_types=["favorite_plays"]))
    result = watcher.run(db, ROWS, NOW, suggestions=SUGGESTIONS)
    selected = [d for d in result.decisions if d.selected]
    assert [d.kind for d in selected] == ["favorite_plays"]
    assert any("desactivado" in d.reason for d in result.decisions if not d.selected)


def test_preferences_migration_and_roundtrip(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.sqlite")
    conn.execute("CREATE TABLE agent_user_preferences (user_id TEXT PRIMARY KEY, favorite_teams TEXT NOT NULL "
                 "DEFAULT '[]', favorite_leagues TEXT NOT NULL DEFAULT '[]', risk_profile TEXT NOT NULL DEFAULT "
                 "'moderate', bankroll REAL NOT NULL DEFAULT 1000.0, updated_at TEXT NOT NULL)")
    conn.execute("INSERT INTO agent_user_preferences VALUES ('default','[\"Chile\"]','[]','moderate',1000,'x')")
    prefs = repo.get_preferences(conn)
    assert prefs.alert_types == DEFAULT_ALERT_TYPES and "near_combo" not in prefs.alert_types
    assert prefs.favorite_teams == ["Chile"] and prefs.browser_notifications is False
    repo.save_preferences(conn, prefs.model_copy(update={"alert_types": ["near_combo"], "alerts_only_favorites": True}))
    again = repo.get_preferences(conn)
    assert again.alert_types == ["near_combo"] and again.alerts_only_favorites
    repo.init_preferences_table(conn)                                   # idempotente
    conn.close()


def test_api_types_filter_and_read_all(db, monkeypatch):
    watcher.run(db, ROWS, NOW, suggestions=SUGGESTIONS)

    path = db.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setattr(router, "connect", lambda: sqlite3.connect(path))
    only = router.get_alerts(user_id="default", unread=False, types="value_bet")
    assert only and {a.kind for a in only} == {"value_bet"}
    router.read_all_alerts(router.ReadAlert(user_id="default"))
    assert router.get_alerts(user_id="default", unread=True, types="") == []
    assert json.loads(db.execute("SELECT facts FROM agent_alerts LIMIT 1").fetchone()[0])


def test_dismissed_alerts_hide_and_do_not_come_back(db, monkeypatch):
    watcher.run(db, ROWS, NOW, suggestions=SUGGESTIONS)
    first = watches.alerts(db, "default")[0]
    path = db.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setattr(router, "connect", lambda: sqlite3.connect(path))
    router.dismiss_alert(first.id, router.ReadAlert(user_id="default"))
    assert first.id not in {a.id for a in watches.alerts(db, "default")}
    with pytest.raises(router.HTTPException):
        router.dismiss_alert(first.id, router.ReadAlert(user_id="default"))      # ya descartado
    watcher.run(db, ROWS, NOW, suggestions=SUGGESTIONS)                           # el vigía no lo reemite
    assert first.id not in {a.id for a in watches.alerts(db, "default")}
    assert len(watches.alerts(db, "default")) == 1
