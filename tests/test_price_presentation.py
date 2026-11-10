"""Los precios ofrecidos no desaparecen ni se describen como cuotas inexistentes."""

import numpy as np
import pytest

from footy.web.services import context


@pytest.mark.parametrize("has_model", [True, False])
def test_offered_prices_remain_visible_without_market_reference(monkeypatch, has_model):
    monkeypatch.setattr(context, "load_params", lambda: {})
    monkeypatch.setattr(context, "league_names", lambda: {"TEST": "Prueba"})
    monkeypatch.setattr(context, "_international_prediction", lambda *a: None)
    monkeypatch.setattr(context, "_cross_probs", lambda *a: np.array([0.5, 0.3, 0.2]) if has_model else None)
    odds = {"1X2": {"DraftKings": {"H": 2.25, "D": 3.2, "A": 3.1}}, "OU": {}, "BTTS": {}}
    result = context._build_context("f:pulido", "TEST", "A", "B", None, odds, offered_only_books={"DraftKings"})
    assert result["odds_1x2"]["DraftKings"] == [2.25, 3.2, 3.1]
    assert result["market_book"] is None
    assert "sin cuotas" not in result["recommendation"]["text"].lower()
    assert "Pinnacle" in result["recommendation"]["text"]
