"""Muestras sintéticas para intervalos y datos faltantes del CLV."""

import pandas as pd
import pytest

from footy_agents.analytics.clv import markdown, summarize


def test_reference_groups_missing_clv_and_cluster_bootstrap():
    bets = pd.DataFrame([
        {"match_id": 1, "market_reference": "Betfair", "clv": -0.1, "profit": -1},
        {"match_id": 2, "market_reference": "Betfair", "clv": -0.1, "profit": 1},
        {"match_id": 3, "market_reference": "Pinnacle", "clv": None, "profit": -1},
    ])
    rows = summarize(bets)
    assert rows[0]["clv"] == pytest.approx(-0.1)
    assert rows[0]["ic95"] == pytest.approx([-0.1, -0.1])
    assert rows[0]["yield"] == 0
    assert rows[1]["n_clv"] == 0 and rows[1]["ic95"] is None
    assert "insuficiente" in markdown(rows)
    assert summarize(pd.DataFrame()) == []
