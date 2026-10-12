import numpy as np
import pytest

from footy.betting import devig
from footy.evaluation import metrics

ODDS = np.array([[2.10, 3.30, 3.60], [1.25, 6.00, 12.0]])


@pytest.mark.parametrize("method", list(devig.METHODS))
def test_devig_sums_to_one_and_preserves_order(method):
    p = devig.devig(ODDS, method)
    assert np.allclose(p.sum(axis=1), 1.0)
    assert (np.argsort(p, axis=1) == np.argsort(1 / ODDS, axis=1)).all()


def test_overround():
    assert devig.overround(np.array([[2.0, 2.0]]))[0] == pytest.approx(0.0)
    assert devig.overround(ODDS)[0] == pytest.approx(1 / 2.1 + 1 / 3.3 + 1 / 3.6 - 1)


def test_power_and_shin_shift_margin_to_longshots():
    prop, pw, sh = (devig.devig(ODDS, m)[1] for m in ("proportional", "power", "shin"))
    # El favorito recibe más probabilidad que con el método proporcional
    assert pw[0] > prop[0] and sh[0] > prop[0]


def test_metrics_perfect_and_uniform():
    y = np.array([0, 1, 2])
    perfect = np.eye(3)
    uniform = np.full((3, 3), 1 / 3)
    assert metrics.log_loss(y, perfect) == pytest.approx(0.0, abs=1e-9)
    assert metrics.brier(y, perfect) == 0.0 and metrics.rps(y, perfect) == 0.0
    assert metrics.log_loss(y, uniform) == pytest.approx(np.log(3))
    assert metrics.brier(y, uniform) == pytest.approx(2 / 3)


def test_rps_penalizes_distant_errors_more():
    y = np.array([0])
    near = np.array([[0.0, 1.0, 0.0]])   # predijo empate, fue local
    far = np.array([[0.0, 0.0, 1.0]])    # predijo visita, fue local
    assert metrics.rps(y, far) > metrics.rps(y, near)


def test_calibration_table_and_ece():
    rng = np.random.default_rng(1)
    p = rng.uniform(0, 1, 20000)
    outcome = rng.uniform(0, 1, 20000) < p      # perfectamente calibrado
    assert metrics.ece(p, outcome) < 0.02
    t = metrics.calibration_table(p, outcome, 10)
    assert t["n"].sum() == 20000 and len(t) == 10


def test_corrupted_exchange_odds_are_not_used_as_reference():
    from footy.betting.devig import clean_1x2, valid_1x2
    assert not valid_1x2([1.31, 3.35, 1.31])                    # margen 82%: precio de Betfair sin liquidez
    assert valid_1x2([2.0, 3.4, 4.0]) and not valid_1x2([0.9, 3.4, 4.0])
    books = {"Betfair Exchange": [3.2, 3.4, 2.4], "Market Avg": [2.2, 3.4, 2.8], "Pinnacle": [2.25, 3.5, 3.0],
             "Bet365": [1.31, 3.35, 1.31]}
    # Betfair con margen posible pero lejos del promedio (0,11 en el local) también queda fuera
    assert set(clean_1x2(books)) == {"Market Avg", "Pinnacle"}
