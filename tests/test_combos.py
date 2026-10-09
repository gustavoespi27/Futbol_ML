import numpy as np
import pytest

from footy.markets import combos
from footy.markets.scoreline import score_matrix


def test_fit_matrix_matches_official_marginals():
    m = combos.fit_matrix(1.6, 1.0, -0.05, p1x2=[0.5, 0.27, 0.23], p_over25=0.45)
    assert m.sum() == pytest.approx(1)
    assert [combos.prob(m, [k]) for k in "1X2"] == pytest.approx([0.5, 0.27, 0.23], abs=1e-4)
    assert combos.prob(m, ["O2.5"]) == pytest.approx(0.45, abs=1e-4)


def test_same_match_probabilities_are_joint_not_product():
    m = combos.fit_matrix(1.5, 1.1)
    p1, po = combos.prob(m, ["1"]), combos.prob(m, ["O2.5"])
    joint = combos.prob(m, ["1", "O2.5"])
    assert joint <= min(p1, po)
    assert joint != pytest.approx(p1 * po, abs=1e-3)          # correlación: ganar local y goles van juntos
    assert combos.prob(m, ["1", "2"]) == 0                       # imposibles
    assert combos.prob(m, ["X", "U1.5", "BTTS_Y"]) == 0          # 1-1 ya son 2 goles
    assert combos.prob(m, ["1X"]) == pytest.approx(combos.prob(m, ["1"]) + combos.prob(m, ["X"]))


def test_suggestions_are_not_redundant_and_sorted():
    m = combos.fit_matrix(1.4, 1.2)
    sug = combos.suggestions(m, top=10)
    assert sug == sorted(sug, key=lambda s: -s["p"])
    for s in sug:
        assert 0.25 <= s["p"] <= 0.85
        assert s["p"] < min(combos.prob(m, [k]) for k in s["keys"]) - 0.02


def test_over_prob_and_calibration():
    lam, mu = np.array([1.3, 2.0]), np.array([0.9, 1.4])
    expected = [score_matrix(a, b)[np.add.outer(np.arange(11), np.arange(11)) > 2.5].sum() for a, b in zip(lam, mu)]
    assert combos.over_prob(lam, mu) == pytest.approx(expected, abs=1e-6)
    p = np.array([0.4, 0.6])
    assert combos.calibrate_over(p) == pytest.approx(p)                                    # sin parámetros
    only_market = {"dc": [1, 0], "blend": [0, 1, 0]}
    assert combos.calibrate_over(p, np.array([0.5, 0.5]), only_market) == pytest.approx([0.5, 0.5])


def test_implied_goals_reproduce_market():
    lam, mu = combos.implied_goals([0.5, 0.27, 0.23], 0.48)
    m = score_matrix(lam, mu)
    assert combos.prob(m, ["1"]) == pytest.approx(0.5, abs=0.02)
    assert lam > mu


def test_pattern_hits_and_combo_odds():
    assert combos.pattern_hits(2, 1, ["1", "O2.5", "BTTS_Y"])
    assert not combos.pattern_hits(1, 1, ["12"])
    assert combos.combo_odds([1.5, 2.0]) == pytest.approx(3.0)
    assert combos.combo_odds([1.5, None]) is None
