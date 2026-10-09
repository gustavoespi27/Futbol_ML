from footy.web import logos


class _Resp:
    def __init__(self, status, content=b"", ctype="image/png"):
        self.status_code, self.content, self.headers = status, content, {"content-type": ctype}


def test_logo_is_downloaded_once_and_missing_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "CACHE", tmp_path)
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp(200, b"\x89PNG" + b"0" * 500) if url.endswith("/teams/451.png") else _Resp(404, b"", "text/html")

    monkeypatch.setattr(logos.requests, "get", fake_get)
    assert logos.get("team", 451).read_bytes().startswith(b"\x89PNG")
    assert logos.get("team", 451) is not None and len(calls) == 1          # segunda vez sale del disco
    assert logos.get("team", 1) is None and logos.get("team", 1) is None
    assert len(calls) == 2                                                  # el que no existe no se repite


def test_league_ids_cover_settings_and_football_data_leagues():
    assert logos.league_api_id("E0") == 39            # de settings.yaml
    assert logos.league_api_id("E1") == 40            # de config/logos.yaml
    assert logos.league_api_id("XXX") is None
