"""Resumen de respaldo construido exclusivamente con textos del turno, sin inferencia."""

from footy_agents.grounding import check_claims, verify_numbers
from footy_agents.names import normalize_name
from footy_agents.observations import observe
from footy_agents.schemas import ToolCallRecord


def verified_summary(records: list[ToolCallRecord], question: str = "") -> str:
    if "cuota" in normalize_name(question):
        analyses = [r for r in records if r.success and r.tool_name == "analyze_match"
                    and isinstance(r.result, dict) and r.result.get("odds_status")]
        if analyses:
            data = analyses[-1].result
            parts = [f"{data.get('home')} vs {data.get('away')}: {data['odds_status']}."]
            parts.extend(f"{o['selection']}: {o['odds']} · {o['bookmaker']}." for o in data.get("best_odds", []))
            text = "\n".join(parts)
            if verify_numbers(text, records).verified and check_claims(text, records).verified:
                return text
    groups: list[list[str]] = [[] for _ in range(7)]
    for record in records:
        data = record.result
        if record.success and record.tool_name == "get_upcoming_matches" and isinstance(data, list):
            for match in data:
                if match.get("home") and match.get("away") and match.get("kickoff_local"):
                    groups[5].append(f"{match['home']} vs {match['away']}: {match['kickoff_local']}.")
            observation = observe(record)
            if observation.status != "ok":
                groups[6].append(observation.note)
        if not record.success or not isinstance(data, dict) or data.get("error"):
            continue
        if record.tool_name == "get_upcoming_matches" and data.get("status") == "empty" and data.get("note"):
            groups[5].append(data["note"])
        if record.tool_name in {"analyze_match", "simulate_match"}:
            probabilities = data.get("probabilities_1x2") or {}
            summary = data.get("summary") or probabilities.get("summary")
            favorite = data.get("favorite") or probabilities.get("favorite")
            if summary:
                groups[0].append(summary)
            if favorite:
                groups[0].append(f"Favorito: {favorite}.")
        for i, key in enumerate(("form_text", "limits_text", "assessment"), 1):
            if data.get(key):
                groups[i].append(data[key])
        if data.get("confirmation_text"):
            groups[3].append(data["confirmation_text"])
        if record.tool_name == "get_coverage":
            for key in ("freshness", "rule"):
                if data.get(key):
                    groups[4].append(data[key])
        observation = observe(record)
        if observation.status != "ok":
            groups[6].append(observation.note)
    text = "\n\n".join(dict.fromkeys(part for group in groups for part in group))
    # Una nota de observación sola no sustituye a los datos útiles solicitados.
    useful = any(groups[i] for i in range(6))
    if useful and verify_numbers(text, records).verified and check_claims(text, records).verified:
        return text
    return ""
