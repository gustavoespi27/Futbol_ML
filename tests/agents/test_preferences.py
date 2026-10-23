"""Pruebas unitarias para el repositorio de preferencias y el servicio de feed personalizado."""

import sqlite3

import pytest

from agents.preferences import repo, service
from agents.schemas import UserPreferences


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    repo.init_preferences_table(conn)
    yield conn
    conn.close()


def test_preferences_defaults(memory_db):
    """Si el usuario no tiene preferencias guardadas, devuelve la configuración predeterminada."""
    prefs = repo.get_preferences(memory_db, "user_1")
    assert prefs.user_id == "user_1"
    assert prefs.favorite_teams == []
    assert prefs.favorite_leagues == []
    assert prefs.risk_profile == "moderate"
    assert prefs.bankroll == 1000.0


def test_preferences_save_and_retrieve(memory_db):
    """Guarda y recupera preferencias personalizadas."""
    custom = UserPreferences(
        user_id="user_1",
        favorite_teams=["Colo-Colo", "Arsenal"],
        favorite_leagues=["CHL", "PL"],
        risk_profile="conservative",
        bankroll=2500.0
    )
    repo.save_preferences(memory_db, custom)

    loaded = repo.get_preferences(memory_db, "user_1")
    assert loaded.user_id == "user_1"
    assert loaded.favorite_teams == ["Colo-Colo", "Arsenal"]
    assert loaded.favorite_leagues == ["CHL", "PL"]
    assert loaded.risk_profile == "conservative"
    assert loaded.bankroll == 2500.0


def test_preferences_update_existing(memory_db):
    """Actualiza preferencias existentes mediante ON CONFLICT DO UPDATE."""
    prefs = UserPreferences(user_id="user_test", favorite_teams=["Boca"])
    repo.save_preferences(memory_db, prefs)

    updated = UserPreferences(user_id="user_test", favorite_teams=["River"], risk_profile="aggressive")
    repo.save_preferences(memory_db, updated)

    loaded = repo.get_preferences(memory_db, "user_test")
    assert loaded.favorite_teams == ["River"]
    assert loaded.risk_profile == "aggressive"


def test_feed_scoring_algorithm(monkeypatch, memory_db):
    """Verifica que el feed ordene primero los partidos con equipos y ligas favoritos."""
    # Guardamos preferencias
    prefs = UserPreferences(
        user_id="user_fan",
        favorite_teams=["Colo-Colo"],
        favorite_leagues=["CHL"],
        risk_profile="moderate"
    )
    repo.save_preferences(memory_db, prefs)

    # Mockeamos service.upcoming y service.current_suggestions
    mock_matches = [
        {
            "ref": "m:100",
            "league": "PL",
            "home": "Chelsea",
            "away": "Liverpool",
            "kickoff": "2026-10-23T15:00:00Z"
        },
        {
            "ref": "m:200",
            "league": "CHL",
            "home": "Colo-Colo",
            "away": "Cobresal",
            "kickoff": "2026-10-23T18:00:00Z"
        },
        {
            "ref": "m:300",
            "league": "CHL",
            "home": "Palestino",
            "away": "Everton",
            "kickoff": "2026-10-23T20:00:00Z"
        }
    ]

    monkeypatch.setattr("footy.web.service.upcoming", lambda: mock_matches)
    monkeypatch.setattr("footy.web.service.current_suggestions", lambda _: {"singles": []})

    feed = service.get_personalized_feed(memory_db, user_id="user_fan")

    assert feed.total_matches == 3
    assert feed.favorite_matches_count == 1
    # Colo-Colo vs Cobresal debe quedar primero por ser equipo favorito (+50) y liga favorita (+25)
    assert feed.items[0].match_id == 200
    assert feed.items[0].is_favorite_team is True
    assert feed.items[0].is_favorite_league is True
    assert feed.items[0].relevance_score >= 85.0

    # Palestino vs Everton debe quedar segundo por ser liga favorita (+25)
    assert feed.items[1].match_id == 300
    assert feed.items[1].is_favorite_team is False
    assert feed.items[1].is_favorite_league is True

    # Chelsea vs Liverpool queda al final
    assert feed.items[2].match_id == 100



def test_feed_favorite_team_exact_match(monkeypatch, memory_db):
    """Ignora acentos, mayúsculas y guiones, pero no acepta coincidencias parciales ('Universidad')."""
    prefs = UserPreferences(user_id="u", favorite_teams=["Ñublense", "Universidad", "Colo-Colo"])
    repo.save_preferences(memory_db, prefs)
    monkeypatch.setattr("footy.web.service.upcoming", lambda: [
        {"ref": "m:1", "league": "CHL", "home": "Nublense", "away": "Everton", "kickoff": "2026-10-23T15:00:00Z"},
        {"ref": "m:2", "league": "CHL", "home": "Universidad de Chile", "away": "", "kickoff": "2026-10-23T18:00:00Z"},
        {"ref": "m:3", "league": "CHL", "home": "Palestino", "away": "Colo Colo", "kickoff": "2026-10-23T20:00:00Z"},
    ])
    monkeypatch.setattr("footy.web.service.current_suggestions", lambda _: {"singles": []})

    feed = service.get_personalized_feed(memory_db, user_id="u")
    flags = {item.match_id: item.is_favorite_team for item in feed.items}
    assert flags == {1: True, 2: False, 3: True}


def test_feed_survives_suggestions_failure(monkeypatch, memory_db):
    """Si el apostador profesional falla, el feed sigue ordenando por preferencias."""
    monkeypatch.setattr("footy.web.service.upcoming", lambda: [
        {"ref": "m:1", "league": "PL", "home": "A", "away": "B", "kickoff": "2026-10-23T15:00:00Z"}])

    def boom(_):
        raise RuntimeError("sin cuotas")
    monkeypatch.setattr("footy.web.service.current_suggestions", boom)

    feed = service.get_personalized_feed(memory_db)
    assert feed.total_matches == 1
    assert feed.items[0].value_bets_count == 0


def test_updated_at_is_utc_z(memory_db):
    """Las fechas se guardan en ISO-8601 UTC con sufijo Z."""
    repo.save_preferences(memory_db, UserPreferences(user_id="z"))
    assert repo.get_preferences(memory_db, "z").updated_at.endswith("Z")
