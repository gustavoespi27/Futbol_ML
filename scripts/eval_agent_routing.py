"""Sondeo reproducible de ruteo con Ollama real y datos controlados, sin escribir en el motor."""

import argparse
import json
import re
import time
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

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
GUSTAVO_CONVERSATION = [
    ("¿Qué apuestas con valor hay hoy?", "get_value_bets"),
    ("que partido importante se juega mañana?", "get_upcoming_matches"),
    ("que tan probable es el partido de chile vs colombia?", "analyze_match"),
    ("cual es la posible apuesta que haya en ese partido?", "analyze_match"),
    ("y no tienes datos de las posibles cuotas?", "analyze_match"),
    ("que otro partido importante hay de selecciones?", "get_upcoming_matches"),
    ("si, busca eso", "get_upcoming_matches"),
    ("que partidos de copa o ligas hay cerca?", "get_upcoming_matches"),
    ("que partidos importantes hay el jueves?", "get_upcoming_matches"),
]
FALLBACK_STEP = "Se entrega el resumen verificado de los datos consultados"


def call_records(events: list) -> list[dict]:
    calls: list[dict] = []
    pending: dict = {}
    for event in events:
        if event.event == "tool_start":
            pending = {"tool": event.data["tool"], "args": event.data.get("args", {})}
        elif event.event == "tool_result":
            calls.append({**pending, "tool": event.data["tool"], "success": event.data["success"]})
            pending = {}
    return calls


def path_correct(expected: str, calls: list[dict], entity: dict, cancel_id: int | None) -> bool:
    """Camino ejecutado con éxito y argumentos del objetivo; no basta con anunciar una herramienta."""
    if expected == "policy":
        return not calls
    successful = [call for call in calls if call["success"]]
    if expected not in [call["tool"] for call in successful]:
        return False
    prerequisites = {"get_upcoming_matches", "find_team", "analyze_match"}
    allowed = {
        "analyze_match": prerequisites | {"get_coverage"},
        "get_team_form": {"find_team", "get_upcoming_matches", "get_team_form"},
        "simulate_match": {"find_team", "get_upcoming_matches", "simulate_match"},
        "get_upcoming_matches": {"get_upcoming_matches"},
        "get_value_bets": {"get_value_bets", "get_coverage", "get_upcoming_matches"},
        "get_coverage": {"get_coverage", "get_upcoming_matches", "get_value_bets"},
        "get_system_performance": {"get_system_performance"},
        "get_stake_limits": {"get_stake_limits"},
        "create_watch": prerequisites | {"create_watch"},
        "list_watches": {"list_watches"},
        "cancel_watch": {"list_watches", "cancel_watch"},
    }
    if any(call["tool"] not in allowed.get(expected, {expected}) for call in calls):
        return False
    own = [call for call in successful if call["tool"] == expected]
    if expected == "create_watch":
        first = next(i for i, call in enumerate(calls) if call["tool"] == "create_watch")
        resolved = any(call["success"] and call["tool"] in {"find_team", "analyze_match"} for call in calls[:first])
        return (
            resolved
            and {c["args"].get("condition") for c in own} == {"kickoff_soon", "pinnacle_available"}
            and all(c["args"].get("match_id") == 181043 for c in own)
        )
    if expected == "cancel_watch":
        return cancel_id is not None and all(c["args"].get("id") == cancel_id for c in own)
    if expected == "get_stake_limits":
        return all(c["args"].get("bankroll") == 100000 for c in own)
    if expected == "analyze_match" and entity.get("match_id"):
        return all(c["args"].get("match_id") == entity["match_id"] for c in own) and all(
            c["tool"] == "analyze_match" for c in calls
        )
    return True


def turn_metrics(events: list, expected: str, entity: dict, cancel_id: int | None) -> dict:
    calls = call_records(events)
    steps = [e.data for e in events if e.event == "step"]
    valid = True
    for call in calls:
        try:
            tools.TOOL_MODELS[call["tool"]].model_validate(call["args"])
        except (ValidationError, KeyError):
            valid = False
    policy = any(step["kind"] == "policy" for step in steps)
    return {
        "tool_correct": expected in [c["tool"] for c in calls] if expected != "policy" else policy,
        "path_correct": path_correct(expected, calls, entity, cancel_id) and (expected != "policy" or policy),
        "args_valid": valid,
        "fallback_used": any(s["text"] == FALLBACK_STEP for s in steps),
        "repairs": sum(s["kind"] == "repair" and s["text"] != FALLBACK_STEP for s in steps),
        "recoveries": sum(s["kind"] == "recovery" for s in steps),
        "calls": calls,
        "manual_interpretation": None,
    }


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3)


def aggregate(results: list[dict]) -> dict:
    return {
        "model": "qwen2.5:7b",
        "n": len(results),
        **{
            key: sum(bool(r.get(key)) for r in results)
            for key in ("tool_correct", "path_correct", "args_valid", "fallback_used")
        },
        "repairs": sum(r.get("repairs", 0) for r in results),
        "recoveries": sum(r.get("recoveries", 0) for r in results),
        "llm_repairs_succeeded": sum(
            bool(r.get("repairs") and r["done"].get("success") and not r.get("fallback_used")) for r in results
        ),
        "recoveries_with_correct_path": sum(bool(r.get("recoveries") and r.get("path_correct")) for r in results),
        "completed": sum(bool(r["done"].get("success")) for r in results),
        "latency_p50_s": percentile([r["elapsed_s"] for r in results], 50),
        "latency_p95_s": percentile([r["elapsed_s"] for r in results], 95),
        "manual_review": "Pendiente: done.success no demuestra interpretación correcta",
    }


def conversation(
    output: Path, cases: list[tuple[str, str]] | None = None, actions: bool = False, closing_run: bool = False
) -> list[dict]:
    """Diez consultas secuenciales, herramientas reales de lectura y memoria SQLite aislada."""
    import sqlite3

    from footy_agents import memory

    client = OpenAICompatibleClient.from_settings()
    if client.model != "qwen2.5:7b":
        raise ValueError("El sondeo requiere qwen2.5:7b")
    results: list[dict] = []
    cases = list(CONVERSATION if cases is None else cases)
    if actions:
        cases += [
            ("Avísame cuando falte poco para Colombia vs Chile y si aparece precio de Pinnacle", "create_watch"),
            ("¿Qué vigilas?", "list_watches"),
            ("", "cancel_watch"),
        ]
    if closing_run:
        cases += [
            ("¿Y quién es favorito?", "analyze_match"),
            ("¿Y ese partido tiene precio de Pinnacle?", "analyze_match"),
        ]
    created_ids: list[int] = []
    with sqlite3.connect(":memory:") as db:
        for question, expected in cases:
            cancel_id = None
            if expected == "cancel_watch":
                if not created_ids:
                    if not closing_run:
                        raise RuntimeError(
                            "No hubo ids reales confirmados por create_watch; no inventar una cancelación"
                        )
                    question = "Deja de vigilar la vigilancia que acabas de crear"
                else:
                    cancel_id = created_ids[-1]
                    question = f"Deja de vigilar la vigilancia {cancel_id}"
            consulted: dict = {}
            prior_entity = memory.recent_entities(db, "eval")
            start = time.perf_counter()
            stream = orchestrator.run_chat(
                client,
                question,
                UserPreferences(),
                history=memory.history(db, "eval"),
                entities=prior_entity,
                consulted_entities=consulted,
            )
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
            correct = (
                expected in path
                if expected != "policy"
                else any(e.event == "step" and e.data["kind"] == "policy" for e in events)
            )
            if expected in {"create_watch", "cancel_watch", "list_watches"}:
                correct = expected in successful and bool(events[-1].data.get("success"))
                if expected == "create_watch":
                    correct = correct and len(created_ids) == 2
            results.append(
                {
                    "question": question,
                    "expected": expected,
                    "path": path,
                    "correct": correct,
                    **turn_metrics(events, expected, prior_entity if question.startswith("¿Y") else {}, cancel_id),
                    "successful_path": successful,
                    "copied_previous": bool(results and answer.strip() == results[-1]["answer"].strip()),
                    "elapsed_s": round(time.perf_counter() - start, 3),
                    "answer": answer,
                    "done": events[-1].data,
                    "events": [e.model_dump() for e in events],
                }
            )
            if events[-1].data.get("success"):
                memory.remember(db, "eval", question, answer, consulted)
            elif consulted:
                memory.remember(db, "eval", question, "", consulted)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            if closing_run:
                output.with_suffix(".metrics.json").write_text(
                    json.dumps(aggregate(results), ensure_ascii=False, indent=2), encoding="utf-8"
                )
            print(
                json.dumps({k: v for k, v in results[-1].items() if k not in {"events", "answer"}}, ensure_ascii=False),
                flush=True,
            )
    return results


def evaluate() -> list[dict]:
    client = OpenAICompatibleClient.from_settings()
    if client.model != "qwen2.5:7b":
        raise ValueError("El sondeo requiere qwen2.5:7b")
    match = {"match_id": 42, "home": "Chile", "away": "Colombia", "league": "WCQ"}
    analysis = {
        **match,
        "probabilities_1x2": {"home_win": "20.0%", "draw": "30.0%", "away_win": "50.0%", "favorite": "Colombia"},
        "has_pinnacle_price": True,
        "value_status": "sin_ventaja",
    }
    entity: dict = {}
    history: list[dict] = []
    results = []
    with (
        patch.object(orchestrator, "upcoming_focus", return_value=None),
        patch.dict(
            tools.TOOLS_REGISTRY,
            {
                "find_team": lambda name: [{"team": "Chile", "exact": True, "next_match": match}],
                "analyze_match": lambda match_id: analysis if match_id == 42 else {"error": "Partido inexistente"},
                "get_upcoming_matches": lambda **kwargs: [analysis],
                "get_team_form": lambda **kwargs: {"team": "Chile", "note": "Sondeo: consulta el partido conocido"},
                "get_coverage": lambda: {"upcoming_matches": 1, "with_pinnacle_price": 1, "stale": False},
            },
        ),
    ):
        for question, expected in [
            ("Analiza el partido de la roja", ["find_team", "analyze_match"]),
            ("¿Y quién es favorito?", ["analyze_match"]),
        ]:
            consulted: dict = {}
            start = time.perf_counter()
            events = list(
                orchestrator.run_chat(
                    client, question, UserPreferences(), history=history, entities=entity, consulted_entities=consulted
                )
            )
            answer = "".join(e.data["delta"] for e in events if e.event == "token")
            path = [e.data["tool"] for e in events if e.event == "tool_start"]
            results.append(
                {
                    "question": question,
                    "expected": expected,
                    "path": path,
                    "correct": path == expected,
                    "elapsed_s": round(time.perf_counter() - start, 3),
                    "answer": answer,
                    "done": events[-1].data,
                    "events": [e.model_dump() for e in events],
                }
            )
            entity = consulted or entity
            if events[-1].data.get("success"):
                history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode",
                        choices=["ruteo", "conversacion", "respaldo", "acciones", "cierre", "gustavo"], default="ruteo")
    args = parser.parse_args()
    if args.mode == "respaldo":
        results = []
        for repeat in (1, 2):
            output = args.output.with_name(f"{args.output.stem}-{repeat}{args.output.suffix}")
            results.extend(
                {**row, "repeat": repeat} for row in conversation(output, [CONVERSATION[i] for i in (0, 1, 4)])
            )
    elif args.mode == "gustavo":
        results = conversation(args.output, GUSTAVO_CONVERSATION)
    elif args.mode == "acciones":
        results = conversation(args.output, actions=True)
    elif args.mode == "cierre":
        results = conversation(args.output, actions=True, closing_run=True)
    else:
        results = conversation(args.output) if args.mode == "conversacion" else evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        print(json.dumps({k: v for k, v in result.items() if k not in {"events"}}, ensure_ascii=False))
