"""Sondeo reproducible de ruteo con Ollama real y datos controlados, sin escribir en el motor."""

import argparse
import json
import time
from pathlib import Path
from unittest.mock import patch

from footy_agents import orchestrator, tools
from footy_agents.llm import OpenAICompatibleClient
from footy_agents.schemas import UserPreferences


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
    args = parser.parse_args()
    results = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        print(json.dumps({k: v for k, v in result.items() if k not in {"events"}}, ensure_ascii=False))
