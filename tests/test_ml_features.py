import numpy as np
import pandas as pd

from footy.features.history import build_features, feature_columns
from footy.models import ml


def _matches():
    rows = []
    t0 = pd.Timestamp("2025-01-01", tz="UTC")
    teams = [(1, 2), (2, 1), (1, 2), (2, 1), (1, 2)]
    goals = [(2, 0), (1, 1), (3, 1), (0, 2), (None, None)]
    for i, ((h, a), (hg, ag)) in enumerate(zip(teams, goals)):
        rows.append({"match_id": i, "comp": "E0", "season": "2025", "kickoff_utc": f"2025-01-{i * 7 + 1:02d}T15:00:00Z",
                     "status": "finished" if hg is not None else "scheduled", "home_id": h, "away_id": a,
                     "home_goals": hg, "away_goals": ag, "h_shots": 10.0, "a_shots": 8.0, "h_sot": 4.0, "a_sot": 3.0,
                     "kickoff": t0 + pd.Timedelta(days=i * 7)})
    return pd.DataFrame(rows)


def test_features_use_only_previous_matches():
    f = build_features(_matches())
    assert np.isnan(f.loc[0, "h_pts_5"])                      # primer partido: sin historial
    assert f.loc[1, "h_pts_5"] == 0 and f.loc[1, "a_pts_5"] == 3   # equipo 2 perdió 2-0; equipo 1 ganó
    assert f.loc[2, "h2h_n"] == 2 and f.loc[2, "h_rest"] == 7
    # El partido programado tiene variables pero su resultado no afecta a nadie
    assert f.loc[4, "h_pts_10"] == np.mean([3, 1, 3, 3])     # equipo 1: G, E (visita), G, G (visita)


def test_design_excludes_odds_market_and_same_match_stats():
    df = build_features(_matches())
    df["b365_H"] = 2.0                                           # columnas que NO deben entrar al modelo
    df["Mercado_pH"] = 0.5
    df["p_over"] = 0.5
    df["Elo_pH"] = 0.4
    cols = list(ml.design(df, use_elo_dc=True, comps=["E0"]).columns)
    assert not any(c.startswith(("b365", "Mercado", "p_over", "pin_", "avg_")) for c in cols)
    assert not {"h_shots", "a_shots", "h_sot", "a_sot", "home_goals", "away_goals"} & set(cols)
    assert "Elo_pH" in cols and "comp" in cols
    assert "Elo_pH" not in ml.design(df, use_elo_dc=False, comps=["E0"]).columns
    assert set(feature_columns(df)) <= set(cols)
