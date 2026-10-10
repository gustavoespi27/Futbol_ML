"""Reglas de valor del modelo propio (footy.betting.suggestions): Kelly, regla original y semáforo.

La cartera oficial del apostador profesional se prueba en test_pro.py; el registro experimental de sugerencias, en
test_experimental_suggestions.py.
"""

import pytest

from footy.betting import suggestions as sg


def test_kelly_stake_is_fractional_with_cap():
    assert sg.stake_fraction(0.5, 2.2) == pytest.approx(0.25 * (0.5 * 2.2 - 1) / 1.2)
    assert sg.stake_fraction(0.4, 2.0) == 0                      # sin valor no se apuesta
    assert sg.stake_fraction(0.9, 2.0) == sg.MAX_STAKE           # tope
    assert sg.growth(0.4, 2.0) == 0
    assert sg.growth(0.55, 2.0) > 0


def test_original_rule_pick_singles_one_per_match():
    cands = [
        {"match": 1, "key": "1", "p": 0.55, "odds": 2.0},                       # EV +10%: sí
        {"match": 1, "key": "O2.5", "p": 0.60, "odds": 1.75},                   # EV +5%: mismo partido, crece menos
        {"match": 2, "key": "2", "p": 0.20, "odds": 6.0},                       # cuota > 4 y p < 25%: no
        {"match": 3, "key": "X", "p": 0.30, "odds": 3.2},                       # EV -4%: no
        {"match": 4, "key": "1X", "p": 0.80, "odds": 1.40, "estimated": True},  # cuota estimada: no
        {"match": 5, "key": "U2.5", "p": 0.80, "odds": 1.25},                   # cuota < 1,30: no
    ]
    picks = sg.pick_singles(cands)
    assert [(p["match"], p["key"]) for p in picks] == [(1, "1")]
    assert picks[0]["risk"] == "medio" and picks[0]["ev"] == pytest.approx(0.10)


def test_pick_doubles_multiplies_and_uses_distinct_matches():
    singles = sg.pick_singles([{"match": i, "key": "1", "p": 0.55, "odds": 2.0} for i in range(3)])
    doubles = sg.pick_doubles(singles)
    assert len(doubles) == 3
    d = doubles[0]
    assert d["p"] == pytest.approx(0.55 ** 2) and d["odds"] == pytest.approx(4.0)
    assert d["legs"][0]["match"] != d["legs"][1]["match"]


def test_traffic_light_verdict_for_markets_without_pinnacle():
    assert sg.verdict(0.55, 2.0)["level"] == "green"                  # +10% de valor, riesgo acotado
    assert sg.verdict(0.55, 2.0, estimated=True)["level"] == "yellow"  # cuota estimada: no se sugiere
    assert sg.verdict(0.20, 6.0)["level"] == "red"                    # probabilidad muy baja
    assert sg.verdict(0.30, 4.5)["level"] == "red"                    # cuota demasiado alta
    assert sg.verdict(0.40, 2.2)["level"] == "red"                    # valor -12%
    assert sg.verdict(0.50, 1.98)["level"] == "yellow"                # precio justo
    assert sg.verdict(0.85, 1.20)["level"] == "yellow"                # paga muy poco
    assert sg.verdict(0.50)["level"] == "none"                        # sin cuota
    assert sg.verdict(0.10)["level"] == "red"
