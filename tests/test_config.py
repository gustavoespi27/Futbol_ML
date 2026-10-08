from footy import config


def test_settings_load_competitions():
    comps = config.settings()["competitions"]
    assert {"ARG", "BRA", "CHL"} <= comps.keys()
    for code, comp in comps.items():
        assert comp["type"] in ("league", "cup"), code


def test_paths_are_inside_project():
    for key in ("raw", "processed", "database"):
        assert config.PROJECT_ROOT in config.path(key).parents
