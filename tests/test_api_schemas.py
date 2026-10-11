"""Contrato de la API con el frontend: los esquemas aceptan cada forma de respuesta y la devuelven sin cambios."""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from footy.web import schemas as s


def roundtrip(tp, data):
    ta = TypeAdapter(tp)
    return json.loads(ta.dump_json(ta.validate_python(data), by_alias=True, exclude_unset=True))


BASE = {"ref": "m:1", "league": "E0", "league_name": "Premier League", "home": "A", "away": "B",
        "kickoff": "2026-10-10T14:00:00Z", "data_through": "2026-10-05T19:00:00Z", "stale": False}
VERDICT = {"level": "yellow", "label": "Neutral", "reason": "Cerca del precio justo"}
FULL = {**BASE, "market_book": "Pinnacle", "home_id": 1, "away_id": 2, "source": "modelo + mercado",
        "p_model": [0.5, 0.3, 0.2], "model_name": "ML historial",
        "form": {"form_h": 2.0, "form_a": None, "gf_h": 1.5, "ga_h": 1.0, "gf_a": None, "ga_a": None, "h2h_n": 0.0,
                 "h2h_pts": None},
        "p_market": [0.48, 0.3, 0.22], "xg": [1.6, 1.1],
        "recommendation": {"bet": True, "sel": 0, "book": "Bet365", "odds": 2.1, "ev": 0.03, "text": "Valor"},
        "pro": [{"key": "1", "sel": "H", "p_fair": 0.48, "fair_odds": 2.08, "pinnacle": 2.0, "odds": 2.1,
                 "book": "Bet365", "edge": 0.01, "bet": False, "stake": 0.0, "growth": 0.0, "risk": "medio",
                 "drift": {"from": 2.1, "to": 2.0, "pct": -0.0476, "n": 3, "signal": "a_favor"}}],
        "has_sharp": True, "p_official": [0.49, 0.29, 0.22], "over25": 0.55, "btts": 0.52,
        "top_scores": [["1-0", 0.11], ["1-1", 0.1]],
        "options": [{"key": "1", "label": "Gana local", "group": "Resultado", "p": 0.49, "fair": 2.08, "odds": 2.1,
                     "book": "Bet365", "estimated": False, "ev": 0.01, "p_fair": 0.48, "verdict": VERDICT},
                    {"key": "BTTS_Y", "label": "Ambos marcan", "group": "Ambos marcan", "p": 0.52, "fair": 1.92,
                     "odds": None, "book": None, "estimated": False, "ev": None, "verdict": VERDICT}],
        "suggestions": [{"keys": ["1", "O1.5"], "label": "Gana local y más de 1,5", "p": 0.4, "fair": 2.5}],
        "odds_1x2": {"Bet365": [2.1, 3.4, 3.6], "Pinnacle": [2.0, 3.5, 3.9]},
        "recent": {"home": ["W", "D", "L", "W", "W"], "away": ["L", "L", "D"]}}
NO_DATA = {**BASE, "market_book": None, "home_id": None, "away_id": None, "source": "sin datos", "p_official": None,
           "options": [], "suggestions": [], "recommendation": {"bet": False, "text": "Sin modelo validado ni cuotas"}}
# Copa sin modelo propio (Champions): probabilidad del mercado (Pinnacle sin margen) y la fase de la copa.
MARKET = {**BASE, "league": "UCL", "league_name": "UEFA Champions League", "market_book": "Pinnacle", "home_id": 1,
          "away_id": 2, "source": "mercado", "p_market": [0.45, 0.27, 0.28], "xg": [1.5, 1.2],
          "recommendation": {"bet": False, "text": "Sin modelo validado en esta liga"}, "pro": [], "has_sharp": False,
          "p_official": [0.45, 0.27, 0.28], "over25": 0.56, "btts": 0.54, "top_scores": [["1-1", 0.12]],
          "options": [], "suggestions": [], "odds_1x2": {"Pinnacle": [2.15, 3.6, 3.45]}, "round": "League Stage - 3"}
ERROR = {**BASE, "source": "error", "error": "equipo sin historial", "options": [], "suggestions": [],
         "recommendation": {"bet": False, "text": "equipo sin historial"}}


@pytest.mark.parametrize("match", [FULL, MARKET, NO_DATA, ERROR], ids=["modelo+mercado", "mercado", "sin datos",
                                                                        "error"])
def test_upcoming_match_shapes_roundtrip_unchanged(match):
    assert roundtrip(list[s.MatchSummary], [match]) == [match]          # sin campos agregados (null) ni perdidos


def test_tracking_summary_without_evaluations_keeps_optional_metrics_absent():
    empty = {"summary": {"evaluated": 0, "pending": 3, "paper_bets": 0}, "matches": [], "bets": []}
    assert roundtrip(s.TrackingOverview, empty) == empty


def test_overview_keeps_reserved_word_field_from():
    ou = {"n": 10, "over_rate": 0.5, "acc_model": 0.5, "acc_official": 0.5, "acc_market": 0.5, "ll_model": 0.69,
          "ll_official": 0.69, "ll_market": 0.69}
    bt = {"n": 100, "leagues": 2, "from": "2026-01-01", "to": "2026-10-01", "acc_model": 0.48, "acc_market": 0.5,
          "acc_official": 0.5, "ll_model": 1.02, "ll_market": 1.0, "ll_official": 1.0, "acc_naive_home": 0.45,
          "ou": ou}
    data = {"backtest": bt, "confidence": [{"range": "60–70%", "n": 5, "pred": 0.65, "hit": 0.6}],
            "tracking": {"evaluated": 0, "pending": 0, "paper_bets": 0}, "last_api_request": None,
            "last_daily_run": "2026-10-09T13:00:00Z", "n_leagues_model": 38, "model_version": "elo_dc_v3",
            "engine": {"ml_model": "poisson_goals", "rho": -0.08366, "n_competitions": 53, "temperature": 1.0,
                       "sharp": "Pinnacle", "min_edge": 0.06, "max_odds": 4.0, "kelly_fraction": 0.25,
                       "max_stake": 0.02, "max_daily": 0.1}}
    assert roundtrip(s.Overview, data) == data


def test_contract_rejects_unknown_or_missing_fields():
    item = {"code": "E0", "name": "Premier League", "country": "Inglaterra", "continent": "Europa",
            "type": "league", "n": 10, "model": True}
    assert roundtrip(list[s.LeagueCatalogItem], [item]) == [item]
    with pytest.raises(ValidationError):
        s.LeagueCatalogItem.model_validate({**item, "nuevo": 1})        # campo no declarado en el contrato
    with pytest.raises(ValidationError):
        s.LeagueCatalogItem.model_validate({k: v for k, v in item.items() if k != "continent"})


def test_cup_without_model_uses_pinnacle_fair_price():
    from footy.web.services.context import _build_context

    odds = {"1X2": {"Pinnacle": {"H": 2.15, "D": 3.6, "A": 3.45}, "Bet365": {"H": 2.4, "D": 3.4, "A": 3.0}},
            "OU": {}, "BTTS": {}}
    ctx = _build_context("s:test", "UCL", "Real Madrid", "Paris SG", None, odds)
    inv = [1 / 2.15, 1 / 3.6, 1 / 3.45]
    assert ctx["source"] == "mercado" and ctx["market_book"] == "Pinnacle"
    assert ctx["p_market"] == pytest.approx([x / sum(inv) for x in inv], abs=1e-3)   # sin margen, nunca del modelo
    assert ctx["has_sharp"] and ctx["recommendation"]["bet"] is False


def test_yesterday_results_use_only_predictions_made_before_kickoff(monkeypatch):
    from datetime import datetime, timedelta

    from footy.db import repository as repo
    from footy.db.connection import connect
    from footy.web.services import context

    conn = connect(":memory:")
    repo.sync_competitions(conn)
    monkeypatch.setattr(context, "connect", lambda: conn)
    noon = datetime.combine(datetime.now(context.LOCAL_TZ).date() - timedelta(days=1), datetime.min.time(),
                            context.LOCAL_TZ) + timedelta(hours=12)
    kickoff = repo.to_iso(noon)
    home = repo.resolve_team(conn, "football_data", "Colo Colo", "Colo Colo", "Chile")
    away = repo.resolve_team(conn, "football_data", "U Chile", "U Chile", "Chile")
    mid = repo.upsert_match(conn, source="api_football", source_match_id="1", season="2026", status="finished",
                            competition_id=repo.competition_id(conn, "CHL"), kickoff_utc=kickoff,
                            home_team_id=home, away_team_id=away, home_goals=2, away_goals=0)
    cup = repo.upsert_match(conn, source="api_football", source_match_id="2", season="2026", status="finished",
                            competition_id=repo.competition_id(conn, "COPA_CHL"), kickoff_utc=kickoff,
                            home_team_id=away, away_team_id=home, home_goals=1, away_goals=1)
    for created, probs in ((noon - timedelta(hours=3), (0.5, 0.3, 0.2)), (noon + timedelta(hours=1), (0.1, 0.2, 0.7))):
        conn.execute("INSERT INTO predictions (match_id, model_version, created_at, p_home, p_draw, p_away) "
                     "VALUES (?, 'v', ?, ?, ?, ?)", (mid, repo.to_iso(created), *probs))
    day = context.played("yesterday")
    out = day["matches"]
    assert [r["ref"] for r in out] == [f"m:{mid}"] and cup != mid      # la copa solo-historial no se muestra
    assert out[0]["score"] == [2, 0] and out[0]["status"] == "finished"
    assert out[0]["pick"] == {"sel": "1", "p": 0.5, "hit": True}       # la predicción posterior al inicio no cuenta
    assert roundtrip(s.PlayedDay, day) == day


def test_play_status_from_stale_database():
    from datetime import datetime, timezone

    from footy.web.services.context import _play_status
    now = datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc)
    assert _play_status("finished", True, "2026-10-11T19:00:00Z", now) == "finished"
    assert _play_status("scheduled", False, "2026-10-11T21:00:00Z", now) == "live"     # empezó hace 1 h
    assert _play_status("live", False, "2026-10-11T18:00:00Z", now) == "pending"       # ya debió terminar
    assert _play_status("postponed", False, "2026-10-11T21:00:00Z", now) == "postponed"
    assert _play_status("live", False, "2026-10-11T18:00:00Z", now, live=True) == "live"  # marcador ESPN reciente


def test_played_today_shows_live_score_and_minute(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from footy.db import repository as repo
    from footy.db.connection import connect
    from footy.web.services import context

    conn = connect(":memory:")
    repo.sync_competitions(conn)
    monkeypatch.setattr(context, "connect", lambda: conn)
    now = datetime.now(timezone.utc)
    kickoff = max(now - timedelta(minutes=50), datetime.combine(now.astimezone(context.LOCAL_TZ).date(),
                                                                 datetime.min.time(), context.LOCAL_TZ))
    h = repo.resolve_team(conn, "espn", "1", "Colo Colo", "Chile")
    a = repo.resolve_team(conn, "espn", "2", "U Chile", "Chile")
    mid = repo.upsert_match(conn, source="espn", source_match_id="9", season="2026", status="live",
                            competition_id=repo.competition_id(conn, "CHL"), kickoff_utc=repo.to_iso(kickoff),
                            home_team_id=h, away_team_id=a)
    conn.execute("INSERT INTO live_scores VALUES (?, 1, 0, ?, ?)", (mid, "50" + chr(39), repo.utc_now()))
    conn.execute("INSERT INTO sync_log VALUES ('espn_live', ?)", (repo.utc_now(),))
    day = context.played("today")
    assert day["live"] is True
    assert day["matches"][0] == {**day["matches"][0], "status": "live", "score": [1, 0], "clock": "50'"}
    assert roundtrip(s.PlayedDay, day) == day
