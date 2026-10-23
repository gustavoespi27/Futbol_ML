"""Router FastAPI para la capa agéntica y preferencias de usuario.

Totalmente desacoplado de footy; solo se monta en app.py si la capa está presente.
"""

from collections.abc import Iterator
from contextlib import closing

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from footy.db.connection import connect
from footy_agents.llm import LLMClient, OpenAICompatibleClient
from footy_agents.orchestrator import run_chat
from footy_agents.preferences import repo, service
from footy_agents.schemas import ChatRequest, PersonalizedFeedResponse, UserPreferences

router = APIRouter(prefix="/api/agent", tags=["Agent"])


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

    def stream() -> Iterator[str]:
        for ev in run_chat(client, req.message, prefs):
            yield ev.to_sse()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
