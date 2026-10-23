"""Router FastAPI para la capa agéntica y preferencias de usuario.

Totalmente desacoplado de footy; solo se monta en app.py si la capa está presente.
"""

from contextlib import closing

from fastapi import APIRouter, Query

from agents.preferences import repo, service
from agents.schemas import PersonalizedFeedResponse, UserPreferences
from footy.db.connection import connect

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
