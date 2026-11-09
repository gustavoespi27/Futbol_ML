"""Compara modelos locales con 15 preguntas fijas y herramientas sobre una ficha sintética estable.

No usa la base real ni APIs deportivas. La inferencia sí es real. No demuestra calidad en datos de producción.
"""

import argparse
import json
import time
from pathlib import Path
from unittest.mock import patch

import requests

from footy import config
from footy_agents import tools
from footy_agents.grounding import verify_numbers
from footy_agents.llm import OpenAICompatibleClient
from footy_agents.orchestrator import run_chat
from footy_agents.schemas import ToolCallRecord, UserPreferences

CASES = [
    ("¿Qué partidos hay en los próximos días?", "get_upcoming_matches"),
    ("¿Cuándo juega Arsenal su próximo partido?", "get_upcoming_matches"),
    ("Dame los próximos 2 partidos de la liga E0.", "get_upcoming_matches"),
    ("¿Qué apuestas con valor frente a Pinnacle hay?", "get_value_bets"),
    ("Busca oportunidades con ventaja mínima de 8%.", "get_value_bets"),
    ("¿Hay alguna apuesta con ventaja superior a 10%?", "get_value_bets"),
    ("Simula Arsenal contra Everton en E0.", "simulate_match"),
    ("¿Cuántos goles esperados tiene Arsenal contra Everton en E0?", "simulate_match"),
    ("Simula Everton como local frente a Arsenal en la liga E0.", "simulate_match"),
    ("¿Cómo va la tabla de la liga E0?", "get_league_standings"),
    ("¿Quién lidera la liga E0?", "get_league_standings"),
    ("Muéstrame los puntos y la racha de Arsenal en la tabla E0.", "get_league_standings"),
    ("¿Cómo está rindiendo el sistema?", "get_system_performance"),
    ("¿Cuál es el CLV del sistema?", "get_system_performance"),
    ("¿Cuántos partidos evaluados y qué yield tiene el seguimiento?", "get_system_performance"),
]


def fixtures() -> dict:
    return {
        "get_upcoming_matches": lambda limit=10, league=None, team=None: [
            {"home": "Arsenal", "away": "Everton", "league": "E0", "kickoff": "2099-01-01T18:00:00Z",
             "probabilities_1x2": {"home_win": "60.0%", "draw": "25.0%", "away_win": "15.0%"}}][:limit],
        "get_value_bets": lambda min_edge=0.06: [
            {"match": "Arsenal vs Everton", "edge": 0.09, "odds": 2.18, "fair_odds": 2.0, "stake": 0.02}
        ] if min_edge <= 0.09 else [],
        "simulate_match": lambda league, home_team, away_team: {
            "home": home_team, "away": away_team, "league": league, "expected_goals": {"home": 1.8, "away": 0.9},
            "probabilities_1x2": {"home_win": 0.60, "draw": 0.25, "away_win": 0.15}},
        "get_league_standings": lambda league: {"league": league, "top_standings": [
            {"position": 1, "team": "Arsenal", "points": 30, "played": 12, "recent": ["W", "W", "D"]}]},
        "get_system_performance": lambda: {"model_version": "v3", "tracking": {
            "evaluated": 400, "bets_yield": "-7.4%", "bets_clv": "-3.0%", "ll_official": 0.9663}},
    }


class MeasuredClient(OpenAICompatibleClient):
    def __init__(self, model: str):
        super().__init__("http://localhost:11434/v1", model, timeout=90, max_tokens=384)
        self.tokens = 0

    def stream_chat(self, messages, spec=None):
        yield from super().stream_chat(messages, spec)
        self.tokens += self.last_usage.get("completion_tokens", 0)


def evaluate(model: str) -> dict:
    client = MeasuredClient(model)
    rows = []
    records = []

    def capture(name, function):
        def wrapped(**kwargs):
            result = function(**kwargs)
            records.append(ToolCallRecord(tool_name=name, arguments=kwargs, result=result, success=True,
                                          execution_time_ms=0))
            return result
        return wrapped

    with patch.dict(tools.TOOLS_REGISTRY, {name: capture(name, fn) for name, fn in fixtures().items()}):
        for question, expected in CASES:
            records.clear()
            start, before = time.perf_counter(), client.tokens
            events = list(run_chat(client, question, UserPreferences()))
            seconds = time.perf_counter() - start
            used = [ev.data["tool"] for ev in events if ev.event == "tool_start"]
            errors = [ev.data["error"] for ev in events if ev.event == "error"]
            answer = "".join(ev.data["delta"] for ev in events if ev.event == "token")
            grounding = verify_numbers(answer, records)
            rows.append({"pregunta": question, "esperada": expected, "usadas": used,
                         "herramienta_correcta": bool(used) and used[0] == expected,
                         "argumentos_validos": any(ev.event == "tool_result" for ev in events)
                         and all(ev.data["success"] for ev in events if ev.event == "tool_result"),
                         "cifras_verificadas": grounding.verified,
                         "segundos": round(seconds, 3), "tokens_s": round((client.tokens - before) / seconds, 2),
                         "errores": errors, "respuesta": answer,
                         "datos_herramientas": [record.model_dump() for record in records]})
            print(f"{model}: {len(rows)}/{len(CASES)} ({seconds:.1f}s)", flush=True)
    response = requests.get("http://localhost:11434/api/ps", timeout=5)
    response.raise_for_status()
    resident = next((m for m in response.json().get("models", []) if m["name"] == model), {})
    # Descargar de memoria entre modelos para que la comparación no mantenga ambos residentes.
    requests.post("http://localhost:11434/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
    return {"modelo": model, "casos": rows, "memoria_modelo_mb": resident.get("size", 0) / 1024**2,
            "vram_modelo_mb": resident.get("size_vram", 0) / 1024**2}


def report(results: list[dict]) -> str:
    lines = ["# Evaluación reproducible de la capa agéntica", "",
             "Ficha sintética fija; 15 preguntas por modelo; inferencia local real. Una ejecución por pregunta. "
             "La primera consulta incluye carga del modelo. Tokens/s = tokens de salida / latencia total "
             "(incluye prompt y herramientas); no es velocidad pura de generación. Memoria según /api/ps, "
             "no RAM total del sistema. La verificación numérica no valida la semántica ni la pertinencia.", ""]
    for result in results:
        lines += [f"## {result['modelo']}", "",
                  f"Memoria del modelo: {result['memoria_modelo_mb']:.0f} MB; "
                  f"VRAM: {result['vram_modelo_mb']:.0f} MB.", "",
                  "| Pregunta | Esperada | Usadas | Argumentos válidos | Cifras verificadas | Segundos | Tokens/s |",
                  "|---|---|---|---|---|---:|---:|"]
        for row in result["casos"]:
            lines.append(f"| {row['pregunta']} | {row['esperada']} | {', '.join(row['usadas']) or 'Ninguna'} | "
                         f"{row['argumentos_validos']} | {row['cifras_verificadas']} | "
                         f"{row['segundos']} | {row['tokens_s']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["qwen2.5:7b", "qwen2.5:3b"])
    parser.add_argument("--output", type=Path, default=config.PROJECT_ROOT / "docs/analisis/08_capa_agentica.md")
    args = parser.parse_args()
    results = []
    for model in args.models:
        results.append(evaluate(model))
        # Guardar tras cada modelo para no perder la primera evaluación si falla la segunda.
        args.output.write_text(report(results), encoding="utf-8")
        args.output.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
