"""Router FastAPI para la capa agéntica y preferencias de usuario.

Totalmente desacoplado de footy; solo se monta en app.py si la capa está presente.
"""

import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from footy.db.connection import connect
from footy.db.repository import utc_now
from footy_agents import memory
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
    PersonalizedFeedResponse,
    UserPreferences,
)

router = APIRouter(prefix="/api/agent", tags=["Agent"])
log = logging.getLogger(__name__)


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
    """Chat con el asistente en streaming SSE: eventos tool_start, tool_result, token, done y error."""
    with closing(connect()) as conn:
        prefs = repo.get_preferences(conn, user_id=req.user_id)
        past = memory.history(conn, req.user_id)
        entities = memory.recent_entities(conn, req.user_id)
    consulted: dict = {}
    return _sse(_recorded(req, run_chat(client, req.message, prefs, history=past, entities=entities,
                                      consulted_entities=consulted), consulted))


def _recorded(req: ChatRequest, events: Iterator[ChatEvent], entities: dict | None = None) -> Iterator[ChatEvent]:
    """Reenvía el stream y, al terminar, guarda el turno en la bitácora y la respuesta verificada en la memoria."""
    started, start = utc_now(), time.perf_counter()
    seen: list[ChatEvent] = []
    for ev in events:
        seen.append(ev)
        yield ev
    done = next((ev.data for ev in reversed(seen) if ev.event == "done"), {})
    answer = "".join(ev.data["delta"] for ev in seen if ev.event == "token")
    try:
        with closing(connect()) as conn:
            memory.log_run(conn, req.user_id, req.message, started, seen, (time.perf_counter() - start) * 1000)
            if done.get("success") and answer.strip():
                memory.remember(conn, req.user_id, req.message, answer, entities)
            elif entities:
                memory.remember(conn, req.user_id, req.message, "", entities)
    except sqlite3.Error as exc:       # la bitácora nunca debe romper una respuesta ya entregada
        log.warning("No se pudo registrar el turno del agente: %s", exc)


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
