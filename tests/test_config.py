from footy import config


def test_settings_load_leagues():
    leagues = config.settings()["leagues"]
    assert {"ARG", "BRA", "CHL"} <= leagues.keys()


def test_paths_are_inside_project():
    for key in ("raw", "processed", "database"):
        assert config.PROJECT_ROOT in config.path(key).parents
