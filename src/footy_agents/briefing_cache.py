"""Resumen persistido por usuario y contenido; generado_at del feed no invalida el caché."""

import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime

from footy import config
from footy.db.connection import connect
from footy.db.repository import utc_now
from footy.web.services.context import LOCAL_TZ
from footy_agents.briefing import facts, run_briefing, template_briefing
from footy_agents.llm import LLMClient
from footy_agents.schemas import ChatEvent, PersonalizedFeedResponse, UserPreferences

_LOCK = threading.Lock()
DDL = """CREATE TABLE IF NOT EXISTS agent_briefing_cache (
    user_id TEXT PRIMARY KEY, signature TEXT NOT NULL, events TEXT NOT NULL, captured_at TEXT NOT NULL
)"""
DAILY_DDL = """CREATE TABLE IF NOT EXISTS agent_briefing_attempts (
    user_id TEXT NOT NULL, local_day TEXT NOT NULL, PRIMARY KEY(user_id, local_day)
)"""


def local_day() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


def cached_briefing(client: LLMClient, prefs: UserPreferences,
                    feed: PersonalizedFeedResponse) -> Iterator[ChatEvent]:
    cfg = config.settings().get("agents", {})
    use_llm = cfg.get("briefing", {}).get("use_llm", False)
    factual = facts(feed)
    day = local_day()
    payload = {"version": 2, "facts": factual, "preferences": prefs.model_dump(exclude={"updated_at"}),
               "day": day if use_llm else None,
               "llm": cfg.get("llm", {}) if use_llm else None, "use_llm": use_llm}
    signature = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    # Un resumen se genera una sola vez; la inferencia sigue protegida por el semáforo compartido con chat.
    with _LOCK, closing(connect()) as conn:
        conn.execute(DDL)
        conn.execute(DAILY_DDL)
        row = conn.execute("SELECT signature, events FROM agent_briefing_cache WHERE user_id = ?",
                           (prefs.user_id,)).fetchone()
        if row and row[0] == signature:
            events = [ChatEvent.model_validate(ev) for ev in json.loads(row[1])]
        else:
            allowed = False
            if use_llm:
                allowed = conn.execute("INSERT OR IGNORE INTO agent_briefing_attempts VALUES (?, ?)",
                                       (prefs.user_id, day)).rowcount == 1
                # Reservar antes de inferir: un reinicio o fallo no permite múltiples redacciones al día.
                conn.commit()
            if allowed:
                events = list(run_briefing(client, prefs, feed))
            else:
                events = [ChatEvent(event="token", data={"delta": template_briefing(factual)}),
                          ChatEvent(event="done", data={"iterations": 0, "success": True})]
            # No persistir fallos transitorios: una próxima visita puede recuperar la IA.
            if events[-1].data.get("success"):
                conn.execute("INSERT INTO agent_briefing_cache VALUES (?, ?, ?, ?) "
                             "ON CONFLICT(user_id) DO UPDATE SET signature=excluded.signature, "
                             "events=excluded.events, captured_at=excluded.captured_at",
                             (prefs.user_id, signature, json.dumps([e.model_dump() for e in events]), utc_now()))
                conn.commit()
    yield from events
