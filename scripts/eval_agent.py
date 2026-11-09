"""Compara modelos locales con 15 preguntas fijas y herramientas sobre una ficha sintética estable.

No usa la base real ni APIs deportivas. La inferencia sí es real. No demuestra calidad en datos de producción.
"""

import argparse
import json
import re
import time
from pathlib import Path
from unittest.mock import patch

import requests

from footy import config
from footy_agents import orchestrator, tools
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
REVISION_CASES = [
    ("¿Qué partidos hay hoy y hay alguno con valor?", "get_value_bets"),
    ("¿Cómo va Colo-Colo en la tabla?", "get_league_standings"),
    ("¿Qué tan fiable es el sistema?", "get_system_performance"),
    ("¿Cuánto debería apostar si tengo 100.000 pesos?", "get_stake_limits"),
    ("¿Quién gana el Real Madrid vs Barcelona?", "simulate_match"),
    ("Dame una combinada segura para hoy", ""),
    ("¿Qué probabilidad tiene Botosani de ganar?", "get_upcoming_matches"),
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


def service_fixtures() -> dict:
    """Mismos datos de entrada para comparar el código anterior y el corregido, sin usar la DB."""
    teams = [("Arsenal", "Everton", "E0", [.6, .25, .15], [{"bet": True, "edge": .09}]),
             ("FC Botosani", "Otelul", "ROU", [.53, .24, .23], [{"bet": False, "edge": -.02}]),
             ("Kristiansund", "Valerenga", "NOR", [.55, .25, .2], []),
             ("Colo-Colo", "Everton Chile", "CHL", [.6, .25, .15], []),
             ("Real Madrid", "Barcelona", "SP1", [.45, .3, .25], [])]
    raw = [{"ref": f"m:{i + 1}", "home": h, "away": a, "league": league, "league_name": league,
            "kickoff": "2026-11-09T23:00:00Z", "p_official": p, "source": "modelo",
            "pro": pro, "recommendation": {"text": "Valor marginal según el modelo" if i == 1 else "Sin cuotas"}}
           for i, (h, a, league, p, pro) in enumerate(teams)]
    catalog = [{"code": c, "name": n, "country": country, "type": "league"} for c, n, country in [
        ("E0", "Premier League", "Inglaterra"), ("CHL", "Primera División de Chile", "Chile"),
        ("SP1", "La Liga", "España"), ("ROU", "Superliga Rumanía", "Rumanía"), ("NOR", "Eliteserien", "Noruega")]]
    def standings(league: str) -> dict | None:
        if league not in {r["code"] for r in catalog}:
            return None
        return {"league_name": league, "season": 2026, "rows": [
            {"pos": 1, "name": "Colo-Colo" if league == "CHL" else "Arsenal", "played": 12,
             "points": 30, "gd": 8, "recent": ["W", "W", "D"]}]}
    return {
        "upcoming": lambda: raw,
        "league_catalog": lambda: catalog,
        "current_suggestions": lambda _: {"singles": [{"match": 1, "home": "Arsenal", "away": "Everton",
            "league": "E0", "label": "Gana local", "book": "Casa de prueba", "odds": 2.18,
            "fair_odds": 2, "edge": .09, "stake": .02, "reason": "Precio superior al justo de Pinnacle"}]},
        "standings": standings,
        "predict": lambda league, h, a, _: {"home": h, "away": a, "league": league,
            "p_model": [.45, .3, .25], "xg": [1.4, 1.2], "top_scores": [["1-1", .12]]},
        "overview": lambda: {"model_version": "v3", "tracking": {"evaluated": 400, "bets_yield": -.074,
            "bets_clv": -.03, "ll_official": .9663}, "engine": {}, "last_daily_run": "2026-11-09T12:00:00Z"},
    }


def has_tool_leak(text: str) -> bool:
    return bool(re.search(r"CallCheck|Llamando a la herramienta|\b(?:get_\w+|simulate_match)\b", text, re.I))


def no_value_without_price(answer: str, records: list[ToolCallRecord]) -> bool:
    """Criterio conservador de evaluación por oración; no demuestra veracidad semántica completa."""
    for record in records:
        if record.tool_name != "get_upcoming_matches" or not isinstance(record.result, list):
            continue
        for row in record.result:
            if row.get("has_pinnacle_price", row.get("has_odds", False)):
                continue
            for sentence in re.split(r"[;\n.!?]", answer.lower()):
                if any(row.get(k, "").lower() in sentence for k in ("home", "away")) and "valor" in sentence:
                    if not re.search(r"sin (?:cuotas|precio|referencia)|no (?:se puede|puedo)|falta", sentence):
                        return False
    return True


class MeasuredClient(OpenAICompatibleClient):
    def __init__(self, model: str):
        super().__init__("http://localhost:11434/v1", model, timeout=90, max_tokens=384)
        self.tokens = 0

    def stream_chat(self, messages, spec=None):
        yield from super().stream_chat(messages, spec)
        self.tokens += self.last_usage.get("completion_tokens", 0)


def evaluate(model: str, revision_only: bool = False) -> dict:
    client = MeasuredClient(model)
    rows = []
    records = []

    original = tools.execute_tool
    def capture(name, arguments):
        record = original(name, arguments)
        records.append(record)
        return record

    selected = REVISION_CASES if revision_only else CASES + REVISION_CASES
    with patch.multiple(tools.service, **service_fixtures()), patch.object(orchestrator, "execute_tool", capture):
        for question, expected in selected:
            records.clear()
            start, before = time.perf_counter(), client.tokens
            events = list(run_chat(client, question, UserPreferences()))
            seconds = time.perf_counter() - start
            used = [ev.data["tool"] for ev in events if ev.event == "tool_start"]
            errors = [ev.data["error"] for ev in events if ev.event == "error"]
            answer = "".join(ev.data["delta"] for ev in events if ev.event == "token")
            try:
                grounding = verify_numbers(answer, records, user_message=question)
            except TypeError:  # comparación explícita con el código anterior, que no acepta user_message
                grounding = verify_numbers(answer, records)
            rows.append({"pregunta": question, "esperada": expected, "usadas": used,
                         "herramienta_correcta": expected in used if expected else True,
                         "argumentos_validos": (not expected or any(ev.event == "tool_result" for ev in events))
                         and all(ev.data["success"] for ev in events if ev.event == "tool_result"),
                         "cifras_verificadas": grounding.verified,
                         "sin_fugas": not has_tool_leak(answer),
                         "sin_valor_sin_precio": no_value_without_price(answer, records),
                         "explica_riesgo_combinada": ("combinadas" in answer.lower() and "segur" in answer.lower()
                             and bool(re.search(r"\bno\b|ninguna|riesgo", answer, re.I))) if not expected else True,
                         "success": events[-1].data.get("success", False),
                         "segundos": round(seconds, 3), "tokens_s": round((client.tokens - before) / seconds, 2),
                         "errores": errors, "respuesta": answer,
                         "datos_herramientas": [record.model_dump() for record in records]})
            print(f"{model}: {len(rows)}/{len(selected)} ({seconds:.1f}s)", flush=True)
    response = requests.get("http://localhost:11434/api/ps", timeout=5)
    response.raise_for_status()
    resident = next((m for m in response.json().get("models", []) if m["name"] == model), {})
    # Descargar de memoria entre modelos para que la comparación no mantenga ambos residentes.
    requests.post("http://localhost:11434/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
    return {"modelo": model, "casos": rows, "memoria_modelo_mb": resident.get("size", 0) / 1024**2,
            "vram_modelo_mb": resident.get("size_vram", 0) / 1024**2}


def report(results: list[dict]) -> str:
    lines = ["# Evaluación reproducible de la capa agéntica", "",
             "Ficha sintética fija; inferencia local real. Una ejecución por pregunta. "
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
        lines += ["", "| Criterio | Casos aprobados |", "|---|---:|"]
        for key in ("herramienta_correcta", "sin_fugas", "sin_valor_sin_precio",
                    "explica_riesgo_combinada", "success"):
            lines.append(f"| {key} | {sum(bool(row[key]) for row in result['casos'])}/{len(result['casos'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["qwen2.5:7b", "qwen2.5:3b"])
    parser.add_argument("--output", type=Path, default=config.PROJECT_ROOT / "docs/analisis/08_capa_agentica.md")
    parser.add_argument("--revision-only", action="store_true", help="Solo las siete preguntas de la revisión en vivo")
    args = parser.parse_args()
    results = []
    for model in args.models:
        results.append(evaluate(model, args.revision_only))
        # Guardar tras cada modelo para no perder la primera evaluación si falla la segunda.
        args.output.write_text(report(results), encoding="utf-8")
        args.output.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
