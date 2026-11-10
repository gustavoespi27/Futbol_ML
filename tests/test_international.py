"""Elo, alias exhaustivos, Poisson y causalidad temporal de selecciones absolutas."""

import json
import pickle
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from footy.db.connection import connect
from footy.ingest import international as src
from footy.models import international as model


def match(year=2000, day=1, hg=2, ag=0, neutral=True):
    kickoff = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1)
    return src.InternationalMatch(kickoff, kickoff + timedelta(hours=3), "France", "Brazil", hg, ag,
                                   "Friendly", neutral)


@pytest.fixture
def fitted():
    rows = [match(day=1 + i * 3, hg=i % 4, ag=(i + 1) % 3) for i in range(36)]
    return model.fit(rows, src.TeamNames())


@pytest.mark.parametrize("name,k", [("Friendly", 20), ("Amistosos internacionales", 20),
    ("Otros", 30), ("UEFA Nations League", 40), ("FIFA World Cup qualification", 40),
    ("Eliminatorias Sudamericanas", 40), ("FIFA World Cup", 60), ("WC", 60), ("UEFA Euro", 50),
    ("Copa América", 50), ("AFC Asian Cup", 50), ("CONCACAF Gold Cup", 50), ("OFC Nations Cup", 50)])
def test_tournament_weight(name, k):
    assert model.tournament_k(name) == k


def test_neutral_home_advantage_and_goal_multiplier():
    histories, differences = model.elo_history([match(neutral=True)])
    assert differences.tolist() == [0]
    assert histories["France"][1].tolist() == [1515]  # 20 × 1,5 × (1 − 0,5)
    assert histories["Brazil"][1].tolist() == [1485]
    assert model.elo_history([match(neutral=False)])[1].tolist() == [100]
    assert model.elo_history([match(neutral=None)])[1].tolist() == [0]


def test_same_day_results_are_not_visible_and_order_is_required():
    first = match()
    second = replace(match(), kickoff=first.kickoff + timedelta(hours=1),
                     available_at=first.available_at + timedelta(hours=1))
    assert model.elo_history([first, second])[1].tolist() == [0, 0]
    with pytest.raises(ValueError, match="ordenados"):
        model.elo_history([second, first])


def test_rating_is_strictly_before_result_availability(fitted):
    item = match()
    histories, _ = model.elo_history([item])
    fitted.histories = histories
    assert fitted.rating_at("France", item.available_at) == 1500
    assert fitted.rating_at("France", item.available_at + timedelta(seconds=1)) == 1515
    assert fitted.rating_at("Tuvalu", item.available_at) == 1500


def test_held_out_result_never_changes_its_prediction_or_training_parameters():
    training = [match(day=1 + i * 3, hg=i % 4, ag=(i + 1) % 3) for i in range(36)]
    held_out = match(year=2022)
    first = model.fit([*training, held_out], src.TeamNames())
    second = model.fit([*training, replace(held_out, home_goals=9)], src.TeamNames())
    assert first.n_train == second.n_train == 36
    assert (first.intercept, first.slope) == (second.intercept, second.slope)
    assert np.allclose(first.predict("France", "Brazil", held_out.kickoff)[0],
                       second.predict("France", "Brazil", held_out.kickoff)[0])
    december = replace(match(year=2021, day=365, hg=9),
                       available_at=datetime(2022, 1, 2, tzinfo=timezone.utc))
    delayed = model.fit([*training, december], src.TeamNames())
    assert delayed.n_train == 36
    assert (delayed.intercept, delayed.slope) == (first.intercept, first.slope)


def test_prediction_symmetry_and_rejection(fitted):
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    home, lam, mu = fitted.predict("France", "Brazil", when, True)
    away, _, _ = fitted.predict("Brazil", "France", when, True)
    assert home.sum() == pytest.approx(1)
    assert np.allclose(home, away[::-1]) and lam > 0 and mu > 0
    with pytest.raises(ValueError):
        fitted.predict("France U21", "Brazil", when)
    with pytest.raises(ValueError):
        model.fit([match(year=2022)], src.TeamNames())


def test_all_names_from_real_database_fixture_resolve_or_are_explicitly_excluded():
    names = src.TeamNames()
    rows = json.loads((Path(__file__).parent / "fixtures/international_db_teams.json").read_text(encoding="utf-8"))
    resolved = [names.canonical(name) for name in rows]
    assert sum(name is not None for name in resolved) == 208
    assert sum(name is None for name in resolved) == 159
    assert names.canonical("ChInEsE Taipei") == "Taiwan"
    assert names.canonical("Türkiye") == "Turkey"
    with pytest.raises(ValueError, match="sin alias"):
        names.canonical("Selección nueva sin mapear")


@pytest.mark.parametrize("name", ["Chile U23", "Brazil U20", "France Sub-17", "France Women", "Brazil W",
                                  "Chile femenino", "England B", "Alanyaspor", "Hull"])
def test_non_senior_or_club_is_excluded(name):
    assert src.TeamNames().canonical(name) is None


def write_csv(path: Path, **changes):
    row = {"date": "2000-01-01", "home_team": "France", "away_team": "Brazil", "home_score": "2",
           "away_score": "0", "tournament": "Friendly", "neutral": "TRUE", **changes}
    path.write_text(",".join(row) + "\n" + ",".join(row.values()) + "\n", encoding="utf-8")


def test_csv_without_hours_waits_two_utc_days(tmp_path):
    path = tmp_path / "results.csv"
    write_csv(path)
    result = src.read_results(path)[0]
    assert result.available_at == result.kickoff + timedelta(days=2)
    write_csv(path, home_team="France U23")
    assert src.read_results(path) == []
    write_csv(path, neutral="unknown")
    with pytest.raises(ValueError):
        src.read_results(path)
    write_csv(path, home_score="-1")
    with pytest.raises(ValueError):
        src.read_results(path)
    with pytest.raises(ValueError):
        replace(match(), available_at=match().kickoff)
    with pytest.raises(ValueError):
        replace(match(), kickoff=datetime(2000, 1, 1))


def database():
    conn = connect(":memory:")
    conn.execute("INSERT INTO competitions VALUES (1,'FRIENDLY','Friendly','World','international')")
    conn.executemany("INSERT INTO teams VALUES (?,?,'World')", [(1, "France"), (2, "Brazil"), (3, "France U23")])
    return conn


def insert_match(conn, mid, kickoff, home=1, hg=2, ag=0):
    conn.execute("INSERT INTO matches (id,competition_id,season,kickoff_utc,home_team_id,away_team_id,status,"
                 "home_goals,away_goals,created_at,updated_at) VALUES (?,1,'2026',?,?,2,'finished',?,?,'a','a')",
                 (mid, kickoff, home, hg, ag))


def test_database_supplement_is_after_csv_and_deduplicates_local_date():
    conn = database()
    insert_match(conn, 1, "2000-01-02T01:00:00Z")
    insert_match(conn, 2, "2000-01-05T18:00:00Z", hg=1)
    insert_match(conn, 3, "2000-01-06T18:00:00Z", home=3)
    rows = src.supplement(conn, [match()], src.TeamNames())
    assert len(rows) == 2 and rows[-1].match_id == 2
    assert rows[-1].available_at == rows[-1].kickoff + timedelta(hours=3)
    assert src.audit_names(conn, src.TeamNames()) == {"resolved": 2, "excluded": 1}
    conn.execute("UPDATE teams SET name='Selección sin alias' WHERE id=1")
    with pytest.raises(ValueError):
        src.audit_names(conn, src.TeamNames())


def test_neutral_policy_is_conservative():
    assert src.neutral_policy("WCQ_SA") is False
    assert src.neutral_policy("UNL", "League A") is False
    assert src.neutral_policy("UNL", "Semi-final") is None
    assert src.neutral_policy("FRIENDLY") is None


def test_artifact_version_corruption_and_memory_cache(tmp_path, monkeypatch, fitted):
    target = tmp_path / "model.pkl"
    monkeypatch.setattr(model, "PATH", target)
    monkeypatch.setattr(model, "_cached", None)
    assert model.load() is None
    target.write_bytes(b"invalid")
    assert model.load() is None
    target.write_bytes(pickle.dumps({"version": "otra", "model": fitted}))
    assert model.load() is None
    target.write_bytes(pickle.dumps({"version": model.VERSION, "model": fitted}))
    first = model.load()
    assert first is not None and model.load() is first


def test_prepare_is_incremental_and_rebuilds_changed_source(tmp_path, monkeypatch):
    path = tmp_path / "results.csv"
    write_csv(path)
    monkeypatch.setattr(src, "refresh_results", lambda **kw: path)
    monkeypatch.setattr(model, "PATH", tmp_path / "model.pkl")
    monkeypatch.setattr(model, "_cached", None)
    conn = database()
    assert model.prepare(conn)["status"] == "actualizado"
    assert model.prepare(conn)["status"] == "sin cambios"
    write_csv(path, home_score="3")
    assert model.prepare(conn)["status"] == "actualizado"
