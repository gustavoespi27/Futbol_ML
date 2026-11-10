"""Historial de conversaciones y memoria personalizada del Míster."""

import sqlite3

import pytest

from footy_agents import conversations, orchestrator, user_memory
from footy_agents.llm import TextDelta
from footy_agents.schemas import ChatEvent, ChatRequest, UserPreferences
from footy_agents.web import router

TEAMS = {"colo colo": "Colo Colo", "la u": "Universidad de Chile", "universidad de chile": "Universidad de Chile"}


def resolve(raw: str) -> str | None:
    return TEAMS.get(raw.strip())


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "chat.sqlite"
    conn = sqlite3.connect(path)
    yield conn, path
    conn.close()


def test_conversation_keeps_what_user_saw_and_titles_from_first_question(db):
    conn, _ = db
    cid = conversations.create(conn, "u")
    conversations.add_turn(conn, "u", cid, "¿Cómo llega Colo Colo a la fecha 30?", "Llega bien.", True,
                           {"team": "Colo Colo"})
    conversations.add_turn(conn, "u", cid, "¿Y la U?", "No pude verificar.", False)
    [listed] = conversations.list_for(conn, "u")
    assert listed.title == "¿Cómo llega Colo Colo a la fecha 30?" and listed.messages == 2
    msgs = conversations.messages(conn, "u", cid)
    assert [m.role for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[-1].content == "No pude verificar." and not msgs[-1].verified
    turns, entities = conversations.context(conn, "u", cid)
    assert turns == [{"role": "user", "content": "¿Cómo llega Colo Colo a la fecha 30?"},
                     {"role": "assistant", "content": "Llega bien."}]      # solo lo verificado vuelve al modelo
    assert entities == {}                                                   # entidades del último turno


def test_conversations_are_private_and_empty_ones_hidden(db):
    conn, _ = db
    cid = conversations.create(conn, "u")
    conversations.create(conn, "u")                                         # vacía: no aparece en el historial
    conversations.add_turn(conn, "otro", cid, "hola", "x", True)            # otro usuario no escribe en ella
    assert conversations.list_for(conn, "u") == []
    assert conversations.messages(conn, "otro", cid) is None
    assert not conversations.delete(conn, "otro", cid) and conversations.delete(conn, "u", cid)


def test_title_is_trimmed():
    assert conversations.title_from("a " * 80).endswith("…")
    assert len(conversations.title_from("a " * 80)) <= conversations.TITLE_CHARS


@pytest.mark.parametrize("message, likes, dislikes", [
    ("Soy hincha de Colo Colo, ¿cómo llega?", ["colo colo"], []),
    ("mi equipo es la U y quiero ver la tabla", ["la u"], []),
    ("ya no sigo a Colo Colo", [], ["colo colo"]),
    ("¿qué partidos hay hoy?", [], []),
])
def test_statements(message, likes, dislikes):
    found_likes, found_dislikes = user_memory.statements(message)
    assert [resolve(x) for x in found_likes] == [resolve(x) for x in likes]
    assert [resolve(x) for x in found_dislikes] == [resolve(x) for x in dislikes]


def test_learns_stated_and_consulted_and_forgets(db):
    conn, _ = db
    learned = user_memory.learn(conn, "u", "Soy hincha de Colo Colo", ["get_team_form"], {"team": "Colo Colo"},
                                resolve)
    assert "sigue a Colo Colo" in learned
    user_memory.learn(conn, "u", "analiza", ["analyze_match"],
                      {"home": "Colombia", "away": "Chile", "league_name": "Amistosos internacionales"}, resolve)
    user_memory.learn(conn, "u", "y Colombia?", ["analyze_match"], {"home": "Colombia", "away": "Brasil"}, resolve)
    by_label = {i.label: i for i in user_memory.items(conn, "u")}
    assert by_label["Colo Colo"].stated and by_label["Colo Colo"].weight == pytest.approx(6.0)
    assert by_label["Colombia"].weight == pytest.approx(2.0) and not by_label["Colombia"].stated
    summary = user_memory.prompt_summary(conn, "u")
    assert "dijo que sigue a Colo Colo" in summary and "consulta seguido a Colombia" in summary
    assert "Brasil" not in summary                                          # una consulta suelta no es un gusto
    assert "análisis de partidos" in summary
    user_memory.learn(conn, "u", "ya no sigo a Colo Colo", [], {}, resolve)
    assert "Colo Colo" not in {i.label for i in user_memory.items(conn, "u")}
    user_memory.forget_all(conn, "u")
    assert user_memory.prompt_summary(conn, "u") == ""


def test_prompt_includes_user_memory_without_numbers():
    base = orchestrator.system_prompt(UserPreferences())
    personal = orchestrator.system_prompt(UserPreferences(), "dijo que sigue a Colo Colo")
    assert "Lo que sabes del usuario" not in base
    assert personal.startswith(base) and "dijo que sigue a Colo Colo" in personal


class OneShot:
    def stream_chat(self, messages, tools=None):
        self.messages = messages
        yield TextDelta("Respuesta del Míster.")


def test_chat_endpoint_saves_turn_in_conversation_and_learns(db, monkeypatch):
    conn, path = db
    monkeypatch.setattr(router, "connect", lambda: sqlite3.connect(path))
    monkeypatch.setattr(router, "resolve_team", resolve)
    cid = router.new_conversation(router.NewConversation(user_id="u")).id
    client = OneShot()
    req = ChatRequest(message="Soy hincha de Colo Colo", user_id="u", conversation_id=cid)
    events = list(router._recorded(req, orchestrator.run_chat(client, req.message, UserPreferences())))
    assert events[-1] == ChatEvent(event="done", data={"iterations": 1, "success": True})
    assert [m.content for m in router.conversation_messages(cid, user_id="u")] == \
        ["Soy hincha de Colo Colo", "Respuesta del Míster."]
    assert [i.label for i in router.profile(user_id="u")] == ["Colo Colo"]
    # Al retomar la conversación, el modelo recibe el turno anterior y lo aprendido del usuario.
    with sqlite3.connect(path) as c2:
        turns, _ = conversations.context(c2, "u", cid)
        known = user_memory.prompt_summary(c2, "u")
    list(orchestrator.run_chat(client, "¿y cómo llega?", UserPreferences(), history=turns, user_memory=known))
    assert "Colo Colo" in client.messages[0]["content"]
    router.delete_conversation(cid, user_id="u")
    assert router.list_conversations(user_id="u", limit=30) == []


def test_past_match_cannot_be_called_next():
    from footy_agents.grounding import check_claims
    from footy_agents.schemas import ToolCallRecord
    form = {"team": "Colo Colo", "last_results": [{"kickoff_local": "dom 08-11, 15:00 hora de Chile",
                                                   "local_date": "2020-11-08", "weekday": "domingo"}]}
    records = [ToolCallRecord(tool_name="get_team_form", arguments={}, result=form, success=True, execution_time_ms=1)]
    bad = check_claims("El próximo partido está programado para el 8 de noviembre contra Ñublense.", records)
    assert not bad.verified and "ya se jugó" in bad.unverified[0]
    assert check_claims("Su último partido fue el 8 de noviembre ante Ñublense.", records).verified
