"""Router FastAPI para la capa agéntica y preferencias de usuario.

Totalmente desacoplado de footy; solo se monta en app.py si la capa está presente.
"""

import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from footy.db.connection import connect
from footy.db.repository import utc_now
from footy_agents import conversations, memory, user_memory, watches
from footy_agents.briefing_cache import cached_briefing
from footy_agents.health import get_health
from footy_agents.llm import LLMClient, OpenAICompatibleClient
from footy_agents.orchestrator import run_chat
from footy_agents.preferences import repo, service
from footy_agents.schemas import (
    AgentHealth,
    AgentRun,
    ChatEvent,
    ChatRequest,
    Conversation,
    ConversationMessage,
    MemoryItem,
    NewConversation,
    PersonalizedFeedResponse,
    UserPreferences,
)
from footy_agents.tools import execute_tool
from footy_agents.watch_schemas import Alert, ReadAlert, Watch, WatchRun

router = APIRouter(prefix="/api/agent", tags=["Agent"])
log = logging.getLogger(__name__)


@router.get("/alerts", response_model=list[Alert])
def get_alerts(user_id: str = Query("default", min_length=1, max_length=100),
               unread: bool = Query(False),
               types: str = Query("", max_length=200, description="Tipos separados por coma")) -> list[Alert]:
    """Avisos vigentes, el partido más cercano primero; `types` filtra por tipo."""
    with closing(connect()) as conn:
        return watches.alerts(conn, user_id, unread, [t.strip() for t in types.split(",") if t.strip()])


@router.post("/alerts/read-all", status_code=204)
def read_all_alerts(body: ReadAlert) -> None:
    with closing(connect()) as conn:
        watches.mark_all_read(conn, body.user_id)


@router.post("/alerts/{id}/dismiss", status_code=204)
def dismiss_alert(id: int, body: ReadAlert) -> None:
    """Descarta un aviso: deja de mostrarse (no se vuelve a emitir el mismo aviso)."""
    with closing(connect()) as conn:
        if not watches.dismiss(conn, body.user_id, id):
            raise HTTPException(status_code=404, detail="Alerta no encontrada")


@router.post("/alerts/{id}/read", status_code=204)
def read_alert(id: int, body: ReadAlert) -> None:
    with closing(connect()) as conn:
        if not watches.mark_read(conn, body.user_id, id):
            raise HTTPException(status_code=404, detail="Alerta no encontrada")


@router.get("/watches", response_model=list[Watch])
def get_watches(user_id: str = Query("default", min_length=1, max_length=100)) -> list[Watch]:
    with closing(connect()) as conn:
        return watches.list_watches(conn, user_id)


@router.get("/watch-log", response_model=list[WatchRun])
def watch_log(limit: int = Query(20, ge=1, le=100),
              user_id: str = Query("default", min_length=1, max_length=100)) -> list[WatchRun]:
    with closing(connect()) as conn:
        return watches.recent_logs(conn, limit, user_id)


@router.get("/health", response_model=AgentHealth)
def health() -> AgentHealth:
    """Disponibilidad del modelo y modo del resumen, con sondeo de un segundo y caché de 60 segundos."""
    return get_health()


@router.get("/preferences", response_model=UserPreferences)
def get_preferences(user_id: str = Query("default", description="Identificador del usuario")) -> UserPreferences:
    """Retorna las preferencias guardadas del usuario o la configuración predeterminada."""
    with closing(connect()) as conn:
        return repo.get_preferences(conn, user_id=user_id)


@router.put("/preferences", response_model=UserPreferences)
def save_preferences(prefs: UserPreferences) -> UserPreferences:
    """Guarda o actualiza las preferencias del usuario."""
    with closing(connect()) as conn:
        repo.save_preferences(conn, prefs)
        return repo.get_preferences(conn, user_id=prefs.user_id)


@router.get("/feed", response_model=PersonalizedFeedResponse)
def get_personalized_feed(
    user_id: str = Query("default", description="Identificador del usuario")
) -> PersonalizedFeedResponse:
    """Genera el feed ordenado y calificado de partidos según las preferencias del usuario."""
    with closing(connect()) as conn:
        return service.get_personalized_feed(conn, user_id=user_id)


def get_llm_client() -> LLMClient:
    """Cliente LLM según settings.yaml (los tests lo reemplazan con dependency_overrides)."""
    return OpenAICompatibleClient.from_settings()


@router.post("/chat")
def chat(req: ChatRequest, client: LLMClient = Depends(get_llm_client)) -> StreamingResponse:
    """Chat con el asistente en streaming SSE: eventos tool_start, tool_result, token, done y error.

    Con `conversation_id` el contexto sale de esa conversación del historial (se puede retomar una antigua);
    sin él se usa la memoria corta por tiempo. Lo aprendido del usuario vuelve al prompt en ambos casos."""
    with closing(connect()) as conn:
        prefs = repo.get_preferences(conn, user_id=req.user_id)
        if req.conversation_id and conversations.owns(conn, req.user_id, req.conversation_id):
            past, entities = conversations.context(conn, req.user_id, req.conversation_id)
        else:
            past, entities = memory.history(conn, req.user_id), memory.recent_entities(conn, req.user_id)
        known = user_memory.prompt_summary(conn, req.user_id)
    consulted: dict = {}
    return _sse(_recorded(req, run_chat(client, req.message, prefs, history=past, entities=entities,
                                      consulted_entities=consulted, user_memory=known), consulted))


def resolve_team(raw: str) -> str | None:
    """Nombre canónico de un equipo mencionado por el usuario, solo si la coincidencia es exacta y única."""
    record = execute_tool("find_team", {"name": raw})
    exact = [r["team"] for r in (record.result or []) if r.get("exact")] if record.success else []
    return exact[0] if len(exact) == 1 else None


def _recorded(req: ChatRequest, events: Iterator[ChatEvent], entities: dict | None = None) -> Iterator[ChatEvent]:
    """Reenvía el stream y, al terminar, guarda el turno: bitácora interna, historial de la conversación (lo que vio
    el usuario), memoria corta verificada y lo aprendido del usuario."""
    started, start = utc_now(), time.perf_counter()
    seen: list[ChatEvent] = []
    for ev in events:
        seen.append(ev)
        yield ev
    done = next((ev.data for ev in reversed(seen) if ev.event == "done"), {})
    answer = "".join(ev.data["delta"] for ev in seen if ev.event == "token")
    shown = answer.strip() or " ".join(ev.data["error"] for ev in seen if ev.event == "error")
    verified = bool(done.get("success") and answer.strip())
    tools_used = [ev.data["tool"] for ev in seen if ev.event == "tool_start"]
    try:
        with closing(connect()) as conn:
            memory.log_run(conn, req.user_id, req.message, started, seen, (time.perf_counter() - start) * 1000)
            if verified:
                memory.remember(conn, req.user_id, req.message, answer, entities)
            elif entities:
                memory.remember(conn, req.user_id, req.message, "", entities)
            if req.conversation_id and shown:
                conversations.add_turn(conn, req.user_id, req.conversation_id, req.message, shown, verified, entities)
            user_memory.learn(conn, req.user_id, req.message, tools_used, entities or {}, resolve_team)
    except sqlite3.Error as exc:       # el registro nunca debe romper una respuesta ya entregada
        log.warning("No se pudo registrar el turno del agente: %s", exc)


@router.get("/conversations", response_model=list[Conversation])
def list_conversations(user_id: str = Query("default", min_length=1, max_length=100),
                       limit: int = Query(30, ge=1, le=100)) -> list[Conversation]:
    """Historial: conversaciones con al menos un mensaje, la más reciente primero."""
    with closing(connect()) as conn:
        return conversations.list_for(conn, user_id, limit)


@router.post("/conversations", response_model=Conversation, status_code=201)
def new_conversation(body: NewConversation) -> Conversation:
    with closing(connect()) as conn:
        conversation_id = conversations.create(conn, body.user_id)
        created = conn.execute("SELECT created_at FROM agent_conversations WHERE id = ?",
                               (conversation_id,)).fetchone()[0]
    return Conversation(id=conversation_id, title="Nueva conversación", created_at=created, updated_at=created,
                        messages=0)


@router.get("/conversations/{conversation_id}", response_model=list[ConversationMessage])
def conversation_messages(conversation_id: int,
                          user_id: str = Query("default", min_length=1, max_length=100)) -> list[ConversationMessage]:
    with closing(connect()) as conn:
        found = conversations.messages(conn, user_id, conversation_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return found


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user_id: str = Query("default", min_length=1, max_length=100)) -> None:
    with closing(connect()) as conn:
        if not conversations.delete(conn, user_id, conversation_id):
            raise HTTPException(status_code=404, detail="Conversación no encontrada")


@router.get("/profile", response_model=list[MemoryItem])
def profile(user_id: str = Query("default", min_length=1, max_length=100)) -> list[MemoryItem]:
    """Lo que el Míster aprendió del usuario (equipos, ligas y temas), lo dicho explícitamente primero."""
    with closing(connect()) as conn:
        return user_memory.items(conn, user_id)


@router.delete("/profile/{item_id}", status_code=204)
def forget_profile_item(item_id: int, user_id: str = Query("default", min_length=1, max_length=100)) -> None:
    with closing(connect()) as conn:
        if not user_memory.forget_item(conn, user_id, item_id):
            raise HTTPException(status_code=404, detail="Recuerdo no encontrado")


@router.delete("/profile", status_code=204)
def forget_profile(user_id: str = Query("default", min_length=1, max_length=100)) -> None:
    with closing(connect()) as conn:
        user_memory.forget_all(conn, user_id)


@router.get("/runs", response_model=list[AgentRun])
def runs(user_id: str = Query("default", description="Identificador del usuario"),
         limit: int = Query(20, ge=1, le=100)) -> list[AgentRun]:
    """Bitácora del agente: últimos turnos con sus herramientas, observaciones, desvíos y reparaciones."""
    with closing(connect()) as conn:
        return memory.recent_runs(conn, user_id, limit)


@router.delete("/memory", status_code=204)
def forget(user_id: str = Query("default", description="Identificador del usuario")) -> None:
    """Empieza una conversación nueva: borra la memoria corta (la bitácora se conserva)."""
    with closing(connect()) as conn:
        memory.forget(conn, user_id)


@router.get("/briefing")
def briefing(user_id: str = Query("default", description="Identificador del usuario"),
             client: LLMClient = Depends(get_llm_client)) -> StreamingResponse:
    """Resumen personalizado de las próximas 24 h en lenguaje natural (SSE: token, done, error)."""
    with closing(connect()) as conn:
        prefs = repo.get_preferences(conn, user_id=user_id)
        feed = service.get_personalized_feed(conn, user_id=user_id)
    return _sse(cached_briefing(client, prefs, feed))


def _sse(events: Iterator[ChatEvent]) -> StreamingResponse:
    return StreamingResponse((ev.to_sse() for ev in events), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
