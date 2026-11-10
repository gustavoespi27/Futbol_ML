"""La traducción es presentación: no altera las identidades ni las consultas."""

from footy.web.team_display import display_text, presentation_payload
from footy_agents import tools


def test_display_keeps_original_payload_and_numbers():
    original = {"match_id": 42, "home": "Czechia", "away": "Spain",
                "summary": "Czechia 9.3% · Spain 90.7%", "items_text": ["Chinese Taipei a 1.30"],
                "nested": {"team": "Spain", "favorite": "Spain"}}
    translated = presentation_payload(original)
    assert original["summary"] == "Czechia 9.3% · Spain 90.7%"
    assert translated["home"] == "Czechia" and translated["away"] == "Spain"
    assert translated["match_id"] == 42
    assert translated["home_display"] == "Chequia"
    assert translated["summary"] == "Chequia 9.3% · España 90.7%"
    assert translated["nested"]["favorite"] == "España"
    assert translated["items_text"] == ["Taiwán a 1.30"]
    assert display_text("Spain U21 vs Spainville") == "España U21 vs Spainville"


def test_find_team_aliases_keep_canonical_identity(monkeypatch):
    matches = [{"ref": "m:42", "home": "Chile", "away": "Spain", "league": "WCQ",
                "kickoff": "2099-11-13T23:00:00Z"}]
    monkeypatch.setattr(tools.service, "upcoming", lambda: matches)
    monkeypatch.setattr(tools.service, "league_catalog", lambda: [])
    for query, canonical in [("la roja", "Chile"), ("Spain", "Spain")]:
        record = tools.execute_tool("find_team", {"name": query})
        assert record.success
        assert record.result[0]["team"] == canonical
        assert record.result[0]["next_match"]["match_id"] == 42
    assert matches[0]["away"] == "Spain"
