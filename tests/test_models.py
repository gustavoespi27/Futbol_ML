import numpy as np
import pandas as pd
import pytest

from footy.betting.backtest import select_bets, simulate
from footy.evaluation.walk_forward import naive_frequencies, walk_forward_dc, walk_forward_elo
from footy.markets.scoreline import markets, outcome_probs, score_matrix
from footy.models.dixon_coles import DixonColes
from footy.models.ensemble import fit_weights, pool


def synthetic_league(n_teams=10, seasons=3, seed=0) -> pd.DataFrame:
    """Liga doble vuelta con fuerzas conocidas; ataque del equipo 0 muy alto."""
    rng = np.random.default_rng(seed)
    att = rng.normal(0, 0.3, n_teams)
    att[0] = 0.8
    dfn = rng.normal(0, 0.3, n_teams)
    rows, t, mid = [], pd.Timestamp("2020-01-04", tz="UTC"), 0
    for _ in range(seasons):
        for rnd in range(2 * (n_teams - 1)):
            perm = rng.permutation(n_teams)
            for h, a in zip(perm[::2], perm[1::2]):
                lam = np.exp(0.15 + 0.25 + att[h] - dfn[a])
                mu = np.exp(0.15 + att[a] - dfn[h])
                rows.append({"match_id": mid, "comp": "X", "season": "s", "kickoff": t,
                             "home_id": int(h), "away_id": int(a),
                             "home_goals": rng.poisson(lam), "away_goals": rng.poisson(mu)})
                mid += 1
            t += pd.Timedelta(days=7)
        t += pd.Timedelta(days=60)
    df = pd.DataFrame(rows)
    df["y"] = np.select([df.home_goals > df.away_goals, df.home_goals == df.away_goals], [0, 1], 2)
    return df


def test_score_matrix_and_markets_are_consistent():
    m = score_matrix(1.6, 1.1, -0.05)
    assert m.sum() == pytest.approx(1.0)
    mk = markets(1.6, 1.1, -0.05)
    assert mk["home"] + mk["draw"] + mk["away"] == pytest.approx(1.0)
    assert outcome_probs(np.array([1.6]), np.array([1.1]), -0.05)[0] == pytest.approx([mk["home"], mk["draw"], mk["away"]])
    assert mk["over_under"][2.5] < mk["over_under"][1.5]
    assert mk["top_scores"][0][1] >= mk["top_scores"][1][1]


def test_dixon_coles_recovers_strengths():
    df = synthetic_league(seasons=4)
    model = DixonColes(xi=0.0, alpha=1e-4).fit(df, df.kickoff.max() + pd.Timedelta(days=1))
    lam, mu = model.expected_goals(np.array([0, 1]), np.array([1, 0]))
    assert lam[0] > lam[1]                        # el equipo 0 marca más de local que el 1
    home_coef = model.glm.coef_[-1]
    assert 0.1 < home_coef < 0.4                  # ventaja local real = 0.25


def test_walk_forward_has_no_lookahead():
    """Cambiar resultados futuros no puede cambiar predicciones pasadas."""
    df = synthetic_league(seasons=2)
    cut = df.kickoff.iloc[len(df) // 2]
    mask = (df.kickoff >= df.kickoff.iloc[len(df) // 3]).to_numpy()
    tampered = df.copy()
    future = tampered.kickoff >= cut
    tampered.loc[future, "home_goals"] = 9
    tampered.loc[future, "y"] = 0

    for fn in (lambda d: walk_forward_dc(d, mask), lambda d: walk_forward_elo(d, mask)):
        a, b = fn(df), fn(tampered)
        before = a.match_id.isin(df.match_id[df.kickoff < cut - pd.Timedelta(days=7)])
        assert np.allclose(a.loc[before, ["pH", "pD", "pA"]], b.loc[before, ["pH", "pD", "pA"]])
        assert not np.allclose(a.loc[~before, ["pH", "pD", "pA"]], b.loc[~before, ["pH", "pD", "pA"]])


def test_naive_frequencies_use_only_previous_days():
    df = synthetic_league(seasons=1)
    P = naive_frequencies(df)
    assert np.allclose(P[0], 1 / 3)               # primer día: solo el prior uniforme
    first_day = df.kickoff == df.kickoff.iloc[0]
    assert np.allclose(P[first_day.to_numpy()], 1 / 3)


def test_pool_weights_prefer_informative_source():
    rng = np.random.default_rng(0)
    truth = rng.dirichlet([2, 2, 2], 3000)
    y = np.array([rng.choice(3, p=p) for p in truth])
    noise = np.full_like(truth, 1 / 3)
    w = fit_weights([truth, noise], y)
    assert w[0] > 0.8
    assert np.allclose(pool([truth, noise], np.array([1.0, 0.0])), truth)


def test_backtest_flat_and_no_bet_rule():
    P = np.array([[0.6, 0.2, 0.2], [0.3, 0.3, 0.4]])
    odds = np.array([[2.0, 4.0, 4.0], [3.0, 3.0, 2.0]])  # EV: 0.2 en el primero; nada > 0 en el segundo
    bets = select_bets(P, odds, min_ev=0.05)
    assert list(bets.idx) == [0] and bets.sel.iloc[0] == 0
    r = simulate(bets, np.array([0, 2]))
    assert r["profit"] == pytest.approx(1.0) and r["yield"] == pytest.approx(1.0)
    k = simulate(bets, np.array([1, 2]), staking="kelly", kelly_fraction=0.25, max_stake=0.05)
    assert k["profit"] == pytest.approx(-100 * 0.05)   # kelly*0.25 = 0.05 -> tope 5%
