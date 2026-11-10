"""Acciones tipadas, identidad del request, sobre de observación y endpoints HTTP reales."""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from footy_agents import orchestrator, routing, tools, watcher, watches
from footy_agents.llm import ToolCall
from footy_agents.observations import observe
from footy_agents.preferences import repo
from footy_agents.schemas import UserPreferences
from footy_agents.watch_schemas import WatchArgs
from footy_agents.web import router


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "actions.sqlite"

    def connect():
        return sqlite3.connect(path)

    with connect() as conn:
        conn.executescript(
            "CREATE TABLE teams(id INTEGER PRIMARY KEY,name TEXT);"
            "INSERT INTO teams VALUES(1,'Chile'),(2,'Colombia');"
            "CREATE TABLE matches(id INTEGER PRIMARY KEY);INSERT INTO matches VALUES(181043);"
        )
    monkeypatch.setattr(tools, "connect", connect)
    monkeypatch.setattr(router, "connect", connect)
    monkeypatch.setattr(tools.service, "upcoming", lambda: [])
    monkeypatch.setattr(tools.service, "league_catalog", lambda: [{"code": "FRI", "name": "Amistosos"}])
    return connect


@pytest.mark.parametrize(
    "name,args",
    [
        ("create_watch", {"condition": "kickoff_soon"}),
        ("create_watch", {"match_id": 1, "team": "Chile", "condition": "kickoff_soon"}),
        ("create_watch", {"match_id": -1, "condition": "kickoff_soon"}),
        ("create_watch", {"match_id": True, "condition": "kickoff_soon"}),
        ("create_watch", {"match_id": 1, "condition": "arbitrary"}),
        ("cancel_watch", {"id": 0}),
        ("cancel_watch", {"id": "1"}),
        ("add_favorite", {}),
        ("add_favorite", {"team": "Chile", "league": "FRI"}),
        ("list_watches", {"user_id": "otro"}),
    ],
)
def test_write_argument_validation_never_calls_tool(name, args, monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("Argumentos inválidos no pueden escribir")

    monkeypatch.setitem(tools.TOOLS_REGISTRY, name, forbidden)
    record = tools.execute_tool(name, args)
    assert not record.success and "Argumentos inválidos" in record.error_message


def test_real_write_tools_and_observation(database):
    def execute(name, args):
        record = tools.execute_tool(name, args, user_id="u")
        assert record.success, record.error_message
        assert observe(record).status == "ok"
        return record.result

    created = execute("create_watch", {"team": "la roja", "condition": "pinnacle_available"})
    assert created["team"] == "Chile"
    assert not execute("create_watch", {"team": "Chile", "condition": "pinnacle_available"})["created"]
    assert execute("list_watches", {})["watches"][0]["id"] == created["id"]
    execute("cancel_watch", {"id": created["id"]})
    assert "No hay" in execute("list_watches", {})["confirmation_text"]
    execute("add_favorite", {"team": "la roja"})
    execute("add_favorite", {"team": "Chile"})
    execute("add_favorite", {"league": "Amistosos"})
    with database() as conn:
        prefs = repo.get_preferences(conn, "u")
        assert prefs.favorite_teams == ["Chile"] and prefs.favorite_leagues == ["FRI"]
        assert not watches.list_watches(conn, "default")
    for name in ("create_watch", "add_favorite"):
        args = {"team": "No existe", **({"condition": "kickoff_soon"} if name == "create_watch" else {})}
        assert not tools.execute_tool(name, args).success
    missing = tools.execute_tool("create_watch", {"match_id": 999, "condition": "kickoff_soon"})
    assert not missing.success and "no existe" in missing.error_message


@pytest.mark.parametrize(
    "message,name,args",
    [
        ("Avísame si aparece valor", "create_watch", {}),
        ("Vigila Chile", "create_watch", {}),
        ("Quiero una alerta", "create_watch", {}),
        ("¿Qué vigilas?", "list_watches", {}),
        ("Mis alertas", "list_watches", {}),
        ("Deja de vigilar el id 12", "cancel_watch", {"id": 12}),
        ("Cancela la vigilancia", "cancel_watch", {}),
        ("Agrega a favoritos Chile", "add_favorite", {"team": "chile"}),
        ("Agrega al cacique a mis favoritos", "add_favorite", {"team": "el cacique"}),
    ],
)
def test_action_routing(message, name, args):
    assert routing.intent_route(message) == (name, args)


def test_chat_creates_two_watches_with_real_ids_and_scoped_user(database, monkeypatch):
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    entity = {"match_id": 181043, "home": "Colombia", "away": "Chile", "summary": "Datos consultados."}
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY, "find_team", lambda name: [{"team": "Chile", "exact": True, "next_match": entity}]
    )
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "analyze_match", lambda match_id: entity)

    class FakeLLM:
        def __init__(self):
            self.turns = iter(
                [
                    [ToolCall("a", "find_team", {"name": "Chile"})],
                    [ToolCall("b", "analyze_match", {"match_id": 181043})],
                    [
                        ToolCall("c", "create_watch", {"match_id": 181043, "condition": "kickoff_soon"}),
                        ToolCall("d", "create_watch", {"match_id": 181043, "condition": "pinnacle_available"}),
                    ],
                ]
            )

        def stream_chat(self, messages, tools=None):
            yield from next(self.turns)

    events = list(
        orchestrator.run_chat(
            FakeLLM(),
            "Avísame cuando falte poco para Colombia vs Chile y si aparece precio de Pinnacle",
            UserPreferences(user_id="u"),
        )
    )
    assert events[-1].data["success"]
    with database() as conn:
        rows = watches.list_watches(conn, "u")
        assert len(rows) == 2 and not watches.list_watches(conn, "default")
    text = "".join(e.data["delta"] for e in events if e.event == "token")
    assert all(f"Vigilancia {w.id}:" in text for w in rows)


def test_http_contracts_and_ownership(database):
    app = FastAPI()
    app.include_router(router.router)
    client = TestClient(app)
    with database() as conn:
        id_ = watches.create_watch(conn, "u", WatchArgs(match_id=181043, condition="pinnacle_available"))["id"]
        # Ficha controlada, no hace peticiones de red ni usa un LLM.
        watcher.run(
            conn,
            [
                {
                    "ref": "m:181043",
                    "home": "Colombia",
                    "away": "Chile",
                    "kickoff": "2099-01-01T00:00:00Z",
                    "odds_1x2": {"Pinnacle": [2, 3, 4]},
                }
            ],
        )
    assert client.get("/api/agent/watches?user_id=u").json()[0]["id"] == id_
    assert client.get("/api/agent/watches?user_id=default").json() == []
    alert = client.get("/api/agent/alerts?user_id=u&unread=true").json()[0]
    assert client.post(f"/api/agent/alerts/{alert['id']}/read", json={"user_id": "otro"}).status_code == 404
    assert client.post(f"/api/agent/alerts/{alert['id']}/read", json={"user_id": "u", "extra": True}).status_code == 422
    assert client.post(f"/api/agent/alerts/{alert['id']}/read", json={"user_id": "u"}).status_code == 204
    assert client.get("/api/agent/alerts?user_id=u&unread=true").json() == []
    assert client.get("/api/agent/alerts?user_id=u").json()[0]["read"]
    log = client.get("/api/agent/watch-log?user_id=u&limit=20").json()[0]
    assert log["actions"] == 1 and log["decisions"][0]["user_id"] == "u"
    assert client.get("/api/agent/watch-log?limit=0").status_code == 422
    assert client.get("/api/agent/watch-log?limit=101").status_code == 422


def test_unsolicited_write_is_rejected_before_execution(database, monkeypatch):
    from footy_agents.llm import TextDelta

    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)

    class FakeLLM:
        def __init__(self):
            self.turns = iter(
                [
                    [ToolCall("a", "create_watch", {"match_id": 181043, "condition": "kickoff_soon"})],
                    [TextDelta("No se solicitó ninguna escritura.")],
                ]
            )

        def stream_chat(self, messages, tools=None):
            yield from next(self.turns)

    events = list(orchestrator.run_chat(FakeLLM(), "Una consulta", UserPreferences()))
    assert any(e.event == "tool_result" and not e.data["success"] for e in events)
    with database() as conn:
        assert not watches.list_watches(conn, "default")


def test_cancel_can_list_first_without_ending_early(database, monkeypatch):
    from footy_agents.llm import TextDelta

    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    with database() as conn:
        id_ = watches.create_watch(conn, "u", WatchArgs(match_id=181043, condition="kickoff_soon"))["id"]

    class FakeLLM:
        def __init__(self):
            self.turns = iter(
                [
                    [ToolCall("a", "list_watches", {})],
                    [TextDelta("Ya consulté las vigilancias.")],
                    [ToolCall("b", "cancel_watch", {"id": id_})],
                ]
            )

        def stream_chat(self, messages, tools=None):
            assert all(t["function"]["name"] in {"cancel_watch", "list_watches", "find_team"} for t in tools)
            yield from next(self.turns)

    events = list(orchestrator.run_chat(FakeLLM(), f"Deja de vigilar el id {id_}", UserPreferences(user_id="u")))
    assert events[-1].data["success"]
    with database() as conn:
        assert watches.list_watches(conn, "u")[0].status == "cancelled"


def test_creation_requires_resolving_before_writing(database, monkeypatch):
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY,
        "analyze_match",
        lambda match_id: {"match_id": match_id, "home": "Colombia", "away": "Chile"},
    )

    class FakeLLM:
        def __init__(self):
            self.index = 0

        def stream_chat(self, messages, tools=None):
            self.index += 1
            if self.index == 1:
                assert {t["function"]["name"] for t in tools} == {"find_team", "analyze_match"}
                yield ToolCall("a", "create_watch", {"match_id": 181043, "condition": "pinnacle_available"})
            elif self.index == 2:
                with database() as conn:
                    assert not watches.list_watches(conn, "u")
                yield ToolCall("b", "analyze_match", {"match_id": 181043})
            else:
                yield ToolCall("c", "create_watch", {"match_id": 181043, "condition": "pinnacle_available"})

    events = list(
        orchestrator.run_chat(FakeLLM(), "Avísame si hay Pinnacle para Colombia vs Chile", UserPreferences(user_id="u"))
    )
    assert events[-1].data["success"]
    with database() as conn:
        assert len(watches.list_watches(conn, "u")) == 1


def test_favorite_with_a_name_is_saved_without_llm(database, monkeypatch):
    saved = []
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "add_favorite", lambda team=None, league=None, user_id="default": (
        saved.append((team, user_id)) or {"status": "ok", "confirmation_text": "Favorito guardado: Chile."}))

    class NoLLM:
        def stream_chat(self, messages, tools=None):
            raise AssertionError("una acción con nombre no necesita inferencia")

    events = list(orchestrator.run_chat(NoLLM(), "Agrega a Chile a mis favoritos", UserPreferences(user_id="u")))
    assert saved == [("chile", "u")]
    assert "".join(e.data["delta"] for e in events if e.event == "token") == "Favorito guardado: Chile."


def test_a_write_the_model_only_claims_is_never_confirmed(database, monkeypatch):
    from footy_agents.llm import TextDelta
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)

    class Claims:
        def stream_chat(self, messages, tools=None):
            yield TextDelta("Listo, quedó vigilando el partido.")       # nunca llama a create_watch

    events = list(orchestrator.run_chat(Claims(), "Avísame si aparece valor en Colombia vs Chile",
                                        UserPreferences(user_id="u")))
    text = "".join(e.data["delta"] for e in events if e.event == "token")
    assert "no se guardó ningún cambio" in text and "Listo" not in text
    assert events[-1].data["success"] is False
    with database() as conn:
        assert not watches.list_watches(conn, "u")
