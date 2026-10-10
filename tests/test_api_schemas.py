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
        "odds_1x2": {"Bet365": [2.1, 3.4, 3.6], "Pinnacle": [2.0, 3.5, 3.9]}}
NO_DATA = {**BASE, "market_book": None, "home_id": None, "away_id": None, "source": "sin datos", "p_official": None,
           "options": [], "suggestions": [], "recommendation": {"bet": False, "text": "Sin modelo validado ni cuotas"}}
ERROR = {**BASE, "source": "error", "error": "equipo sin historial", "options": [], "suggestions": [],
         "recommendation": {"bet": False, "text": "equipo sin historial"}}


@pytest.mark.parametrize("match", [FULL, NO_DATA, ERROR], ids=["modelo+mercado", "sin datos", "error"])
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
            "last_daily_run": "2026-10-09T13:00:00Z", "n_leagues_model": 38, "model_version": "elo_dc_v3"}
    assert roundtrip(s.Overview, data) == data


def test_contract_rejects_unknown_or_missing_fields():
    item = {"code": "E0", "name": "Premier League", "country": "Inglaterra", "continent": "Europa",
            "type": "league", "n": 10, "model": True}
    assert roundtrip(list[s.LeagueCatalogItem], [item]) == [item]
    with pytest.raises(ValidationError):
        s.LeagueCatalogItem.model_validate({**item, "nuevo": 1})        # campo no declarado en el contrato
    with pytest.raises(ValidationError):
        s.LeagueCatalogItem.model_validate({k: v for k, v in item.items() if k != "continent"})
