"""Sondeo reproducible de ruteo con Ollama real y datos controlados, sin escribir en el motor."""

import argparse
import json
import re
import time
from pathlib import Path
from unittest.mock import patch

from footy_agents import orchestrator, tools
from footy_agents.llm import OpenAICompatibleClient
from footy_agents.schemas import UserPreferences

CONVERSATION = [
    ("Analiza el partido de la roja", "analyze_match"),
    ("¿Y quién es favorito?", "analyze_match"),
    ("¿Cómo llega el Colo Colo?", "get_team_form"),
    ("Simula Colo Colo contra la U", "simulate_match"),
    ("que partidos vienen ahora?", "get_upcoming_matches"),
    ("¿Qué apuestas con valor hay hoy?", "get_value_bets"),
    ("¿Por qué no hay apuestas recomendadas?", "get_coverage"),
    ("¿Qué tan fiable es el sistema?", "get_system_performance"),
    ("¿Cuánto debería apostar si tengo 100.000 pesos?", "get_stake_limits"),
    ("Dame una combinada segura para hoy", "policy"),
]


def conversation(output: Path, cases: list[tuple[str, str]] | None = None, actions: bool = False) -> list[dict]:
    """Diez consultas secuenciales, herramientas reales de lectura y memoria SQLite aislada."""
    import sqlite3

    from footy_agents import memory

    client = OpenAICompatibleClient.from_settings()
    if client.model != "qwen2.5:7b":
        raise ValueError("El sondeo requiere qwen2.5:7b")
    results: list[dict] = []
    cases = list(CONVERSATION if cases is None else cases)
    if actions:
        cases += [("Avísame cuando falte poco para Colombia vs Chile y si aparece precio de Pinnacle", "create_watch"),
                  ("¿Qué vigilas?", "list_watches"), ("", "cancel_watch")]
    created_ids: list[int] = []
    with sqlite3.connect(":memory:") as db:
        for question, expected in cases:
            if expected == "cancel_watch":
                if not created_ids:
                    raise RuntimeError("No hubo ids reales confirmados por create_watch; no inventar una cancelación")
                question = f"Deja de vigilar la vigilancia {created_ids[-1]}"
            consulted: dict = {}
            start = time.perf_counter()
            stream = orchestrator.run_chat(client, question, UserPreferences(), history=memory.history(db, "eval"),
                                           entities=memory.recent_entities(db, "eval"), consulted_entities=consulted)
            if actions:
                from footy_agents.schemas import ChatRequest
                from footy_agents.web.router import _recorded
                stream = _recorded(ChatRequest(message=question), stream, consulted)
            events = list(stream)
            answer = "".join(e.data["delta"] for e in events if e.event == "token")
            path = [e.data["tool"] for e in events if e.event == "tool_start"]
            successful = [e.data["tool"] for e in events if e.event == "tool_result" and e.data["success"]]
            if expected == "create_watch":
                created_ids = [int(id_) for id_ in re.findall(r"Vigilancia (\d+):", answer)]
            correct = expected in path if expected != "policy" else any(
                e.event == "step" and e.data["kind"] == "policy" for e in events)
            if expected in {"create_watch", "cancel_watch", "list_watches"}:
                correct = expected in successful and bool(events[-1].data.get("success"))
                if expected == "create_watch":
                    correct = correct and len(created_ids) == 2
            results.append({"question": question, "expected": expected, "path": path, "correct": correct,
                            "successful_path": successful,
                            "copied_previous": bool(results and answer.strip() == results[-1]["answer"].strip()),
                            "elapsed_s": round(time.perf_counter() - start, 3), "answer": answer,
                            "done": events[-1].data, "events": [e.model_dump() for e in events]})
            if events[-1].data.get("success"):
                memory.remember(db, "eval", question, answer, consulted)
            elif consulted:
                memory.remember(db, "eval", question, "", consulted)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in results[-1].items() if k not in {"events", "answer"}},
                             ensure_ascii=False), flush=True)
    return results


def evaluate() -> list[dict]:
    client = OpenAICompatibleClient.from_settings()
    if client.model != "qwen2.5:7b":
        raise ValueError("El sondeo requiere qwen2.5:7b")
    match = {"match_id": 42, "home": "Chile", "away": "Colombia", "league": "WCQ"}
    analysis = {**match, "probabilities_1x2": {"home_win": "20.0%", "draw": "30.0%",
                                            "away_win": "50.0%", "favorite": "Colombia"},
                "has_pinnacle_price": True, "value_status": "sin_ventaja"}
    entity: dict = {}
    history: list[dict] = []
    results = []
    with patch.object(orchestrator, "upcoming_focus", return_value=None), patch.dict(tools.TOOLS_REGISTRY, {
        "find_team": lambda name: [{"team": "Chile", "exact": True, "next_match": match}],
        "analyze_match": lambda match_id: analysis if match_id == 42 else {"error": "Partido inexistente"},
        "get_upcoming_matches": lambda **kwargs: [analysis],
        "get_team_form": lambda **kwargs: {"team": "Chile", "note": "Sondeo: consulta el partido conocido"},
        "get_coverage": lambda: {"upcoming_matches": 1, "with_pinnacle_price": 1, "stale": False},
    }):
        for question, expected in [("Analiza el partido de la roja", ["find_team", "analyze_match"]),
                                   ("¿Y quién es favorito?", ["analyze_match"])]:
            consulted: dict = {}
            start = time.perf_counter()
            events = list(orchestrator.run_chat(client, question, UserPreferences(), history=history,
                                               entities=entity, consulted_entities=consulted))
            answer = "".join(e.data["delta"] for e in events if e.event == "token")
            path = [e.data["tool"] for e in events if e.event == "tool_start"]
            results.append({"question": question, "expected": expected, "path": path, "correct": path == expected,
                            "elapsed_s": round(time.perf_counter() - start, 3), "answer": answer,
                            "done": events[-1].data, "events": [e.model_dump() for e in events]})
            entity = consulted or entity
            if events[-1].data.get("success"):
                history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["ruteo", "conversacion", "respaldo", "acciones"], default="ruteo")
    args = parser.parse_args()
    if args.mode == "respaldo":
        results = []
        for repeat in (1, 2):
            output = args.output.with_name(f"{args.output.stem}-{repeat}{args.output.suffix}")
            results.extend({**row, "repeat": repeat} for row in conversation(
                output, [CONVERSATION[i] for i in (0, 1, 4)]))
    elif args.mode == "acciones":
        results = conversation(args.output, actions=True)
    else:
        results = conversation(args.output) if args.mode == "conversacion" else evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        print(json.dumps({k: v for k, v in result.items() if k not in {"events"}}, ensure_ascii=False))
