"""Sondeo acotado del modelo configurado; no carga el modelo ni ejecuta inferencia."""

import threading
import time

import requests

from footy import config
from footy_agents.ollama_runtime import runtime
from footy_agents.schemas import AgentHealth

TTL = 60
_lock = threading.Lock()
_cache: tuple[tuple, float, AgentHealth] | None = None


def get_health() -> AgentHealth:
    global _cache
    agents = config.settings().get("agents", {})
    llm = agents.get("llm", {})
    base = llm.get("base_url", "http://localhost:11434/v1").rstrip("/")
    model = llm.get("model", "qwen2.5:7b")
    mode = "llm" if agents.get("briefing", {}).get("use_llm", False) else "template"
    autostart = bool(llm.get("autostart", False))
    key = (base, model, mode, autostart, runtime.startup_failed)
    with _lock:
        if _cache and _cache[0] == key and time.monotonic() < _cache[1]:
            return _cache[2].model_copy()
        available = False
        try:
            with requests.get(base + "/models", timeout=1.0) as response:
                response.raise_for_status()
                payload = response.json()
            models = payload.get("data", []) if isinstance(payload, dict) else []
            available = isinstance(models, list) and any(isinstance(item, dict) and item.get("id") == model
                                                        for item in models)
        except (requests.RequestException, ValueError):
            # Servidor apagado, respuesta HTTP fallida o JSON inválido: el resto de la aplicación sigue disponible.
            pass
        health = AgentHealth(llm_available=available, briefing_mode=mode, model=model,
                             autostart=autostart, startup_failed=runtime.startup_failed)
        _cache = (key, time.monotonic() + TTL, health)
        return health.model_copy()
