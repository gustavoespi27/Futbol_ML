"""Cliente LLM con API compatible con OpenAI (Ollama local por defecto, costo cero).

El orquestador solo depende del protocolo `LLMClient`: cambiar de proveedor (Ollama, Groq, Gemini...) es cambiar
`base_url` y `model` en settings.yaml, y los tests usan un cliente simulado sin red ni tokens.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from footy import config


class LLMUnavailable(Exception):
    """El servidor del LLM no responde (apagado, sin el modelo descargado o fuera de tiempo)."""


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""          # texto original si el modelo no entregó JSON válido


LLMEvent = TextDelta | ToolCall


class LLMClient(Protocol):
    def stream_chat(self, messages: list[dict], tools: list[dict] | None = None) -> Iterator[LLMEvent]:
        """Emite fragmentos de texto a medida que llegan y, al final, las llamadas a herramientas pedidas."""
        ...


def _parse_arguments(raw: str) -> tuple[dict[str, Any], str]:
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}, raw
    return (args, "") if isinstance(args, dict) else ({}, raw)


class OpenAICompatibleClient:
    """POST {base_url}/chat/completions con stream=True (formato SSE de OpenAI, que Ollama replica)."""

    def __init__(self, base_url: str, model: str, timeout: float = 120.0, api_key: str | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    @classmethod
    def from_settings(cls) -> "OpenAICompatibleClient":
        cfg = config.settings().get("agents", {}).get("llm", {})
        return cls(cfg.get("base_url", "http://localhost:11434/v1"), cfg.get("model", "qwen2.5:7b"),
                   float(cfg.get("timeout", 120)))

    def stream_chat(self, messages: list[dict], tools: list[dict] | None = None) -> Iterator[LLMEvent]:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True, "temperature": 0.2}
        if tools:
            body["tools"] = tools
        try:
            resp = requests.post(self.url, json=body, headers=self.headers, stream=True, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LLMUnavailable(str(exc)) from exc

        # las llamadas a herramientas pueden llegar en trozos (OpenAI) o completas (Ollama): se acumulan por índice
        pending: dict[int, dict[str, str]] = {}
        with resp:
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    choices = json.loads(payload).get("choices") or [{}]
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        yield TextDelta(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = pending.setdefault(tc.get("index", len(pending)), {"id": "", "name": "", "args": ""})
                        fn = tc.get("function") or {}
                        slot["id"] = tc.get("id") or slot["id"]
                        slot["name"] = fn.get("name") or slot["name"]
                        slot["args"] += fn.get("arguments") or ""
            except requests.RequestException as exc:
                raise LLMUnavailable(str(exc)) from exc
            except json.JSONDecodeError as exc:
                raise LLMUnavailable(f"Respuesta inválida del LLM: {exc}") from exc

        for i, slot in sorted(pending.items()):
            args, raw = _parse_arguments(slot["args"])
            yield ToolCall(id=slot["id"] or f"call_{i}", name=slot["name"], arguments=args, raw_arguments=raw)
