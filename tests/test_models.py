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
    p = outcome_probs(np.array([1.6]), np.array([1.1]), -0.05)[0]
    assert p == pytest.approx([mk["home"], mk["draw"], mk["away"]])
    assert mk["over_under"][2.5] < mk["over_under"][1.5]
    assert mk["top_scores"][0][1] >= mk["top_scores"][1][1]


def test_dixon_coles_recovers_strengths():
    df = synthetic_league(seasons=4)
    model = DixonColes(xi=0.0, alpha=1e-4).fit(df, df.kickoff.max() + pd.Timedelta(days=1))
    lam, mu = model.expected_goals(np.array([0, 1]), np.array([1, 0]))
    assert lam[0] > lam[1]                        # el equipo 0 marca más de local que el 1
    home_coef = model.glm.coef_[-1]
    assert 0.1 < home_coef < 0.4                  # ventaja local real = 0.25


def _dense_design(model, home, away):
    """Matriz de diseño densa original (referencia para la versión dispersa)."""
    n, k = len(home), len(model.teams)
    X = np.zeros((2 * n, 2 * k + 1))
    hi = np.array([model.teams.get(t, -1) for t in home])
    ai = np.array([model.teams.get(t, -1) for t in away])
    rows = np.arange(n)
    for r_off, att, dfn in ((0, hi, ai), (n, ai, hi)):
        ok = att >= 0
        X[rows[ok] + r_off, att[ok]] = 1.0
        ok = dfn >= 0
        X[rows[ok] + r_off, k + dfn[ok]] = -1.0
    X[:n, -1] = 1.0
    return X


def test_dixon_coles_sparse_design_matches_dense(monkeypatch):
    from scipy import sparse

    df = synthetic_league(seasons=3)
    now = df.kickoff.max() + pd.Timedelta(days=1)
    m = DixonColes(xi=0.002, alpha=1e-3).fit(df, now)
    home, away = np.array([0, 1, 99]), np.array([1, 99, 0])       # 99: equipo desconocido = promedio
    X = m._design(home, away)
    assert sparse.issparse(X) and X.format == "csr"
    np.testing.assert_array_equal(X.toarray(), _dense_design(m, home, away))
    monkeypatch.setattr(DixonColes, "_design", lambda self, h, a: _dense_design(self, h, a))
    ref = DixonColes(xi=0.002, alpha=1e-3).fit(df, now)
    np.testing.assert_allclose(m.glm.coef_, ref.glm.coef_, rtol=0, atol=1e-10)
    assert m.glm.intercept_ == pytest.approx(ref.glm.intercept_, abs=1e-10)
    assert m.rho == pytest.approx(ref.rho, abs=1e-10)


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


def test_fit_weights_nonneg_never_inverts_a_source():
    rng = np.random.default_rng(1)
    truth = rng.dirichlet([2, 2, 2], 3000)
    y = np.array([rng.choice(3, p=p) for p in truth])
    noisy = lambda: truth * rng.lognormal(0, 0.5, truth.shape)  # noqa: E731
    d = noisy()
    direct = d / d.sum(1, keepdims=True)
    inv = 1 / noisy()
    anti = inv / inv.sum(1, keepdims=True)                 # informativa al revés: sin restricción, peso < 0
    assert fit_weights([direct, anti], y)[1] < 0
    w = fit_weights([direct, anti], y, nonneg=True)
    assert (w >= 0).all() and w[1] < 0.05


def test_backtest_flat_and_no_bet_rule():
    P = np.array([[0.6, 0.2, 0.2], [0.3, 0.3, 0.4]])
    odds = np.array([[2.0, 4.0, 4.0], [3.0, 3.0, 2.0]])  # EV: 0.2 en el primero; nada > 0 en el segundo
    bets = select_bets(P, odds, min_ev=0.05)
    assert list(bets.idx) == [0] and bets.sel.iloc[0] == 0
    r = simulate(bets, np.array([0, 2]))
    assert r["profit"] == pytest.approx(1.0) and r["yield"] == pytest.approx(1.0)
    k = simulate(bets, np.array([1, 2]), staking="kelly", kelly_fraction=0.25, max_stake=0.05)
    assert k["profit"] == pytest.approx(-100 * 0.05)   # kelly*0.25 = 0.05 -> tope 5%


def test_dixon_coles_shot_mix_uses_shots_without_leakage():
    df = synthetic_league(seasons=3, seed=2)
    rng = np.random.default_rng(3)
    # Tiros correlacionados con goles: ~0.3 goles por tiro al arco
    df["h_sot"] = df.home_goals * 2 + rng.poisson(2, len(df))
    df["a_sot"] = df.away_goals * 2 + rng.poisson(2, len(df))
    df["h_shots"] = df.h_sot + rng.poisson(5, len(df))
    df["a_shots"] = df.a_sot + rng.poisson(5, len(df))
    now = df.kickoff.max() + pd.Timedelta(days=1)
    m = DixonColes(xi=0.0, alpha=1e-4, mix=0.5).fit(df, now)
    assert m.shot_coefs is not None and m.shot_coefs[0] > m.shot_coefs[1] >= 0
    P = m.predict(df.head(5))["P"]
    assert np.allclose(P.sum(axis=1), 1)
    # Sin estadísticas cae a solo goles
    m2 = DixonColes(xi=0.0, alpha=1e-4, mix=0.5).fit(df.assign(h_sot=np.nan, a_sot=np.nan), now)
    assert m2.shot_coefs is None


def test_goal_markets_come_from_one_coherent_score_matrix():
    from footy.markets.scoreline import score_matrix
    from footy.models import ml

    lam, mu, rho = np.array([1.6, 0.9]), np.array([1.1, 1.4]), -0.08
    P = ml.goal_markets(lam, mu, rho)
    np.testing.assert_allclose(P["1x2"].sum(1), 1)
    for i in range(2):
        M = score_matrix(lam[i], mu[i], rho)
        tot = np.add.outer(np.arange(M.shape[0]), np.arange(M.shape[1]))
        assert P["1x2"][i] == pytest.approx([np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()])
        assert P["over25"][i] == pytest.approx(M[tot > 2.5].sum())
        assert P["btts"][i] == pytest.approx(M[1:, 1:].sum())


def test_poisson_goal_model_learns_expected_goals_without_future_rows():
    from footy.models import ml

    rng = np.random.default_rng(1)
    n = 6000
    days = np.sort(rng.integers(0, 365 * 12, n))
    kick = pd.Timestamp("2014-08-01", tz="UTC") + pd.to_timedelta(days, unit="D")
    att_h, att_a = rng.normal(0, 0.35, n), rng.normal(0, 0.35, n)
    df = pd.DataFrame({"comp": "X", "kickoff_utc": kick.strftime("%Y-%m-%dT%H:%M:%SZ"), "h_att": att_h, "a_att": att_a,
                       "home_goals": rng.poisson(np.exp(0.35 + att_h)), "away_goals": rng.poisson(np.exp(0.1 + att_a))})
    model, P_valid = ml.fit(df, use_elo_dc=False, log=lambda *a: None)
    lam, mu = model.goals(pd.DataFrame({"comp": "X", "h_att": [0.6, -0.6], "a_att": [0.0, 0.0]}))
    assert lam[0] > lam[1] and abs(mu[0] - mu[1]) < 0.15        # el ataque del local sube λ y no μ
    _, va = ml._rows(df, False)
    assert len(P_valid["1x2"]) == va.sum() and -0.2 <= model.rho <= 0.2
