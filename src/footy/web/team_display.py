"""Nombres públicos: nunca se usan para resolver equipos ni para escribir en la base."""

import json
import re
from pathlib import Path
from typing import Any

DISPLAY_NAMES: dict[str, str] = json.loads(
    Path(__file__).with_name("static").joinpath("team-display.json").read_text(encoding="utf-8"))
_PATTERN = re.compile(r"(?<!\w)(?:" + "|".join(
    re.escape(name) for name in sorted(DISPLAY_NAMES, key=len, reverse=True)) + r")(?!\w)")


def display_text(text: str) -> str:
    return _PATTERN.sub(lambda match: DISPLAY_NAMES[match[0]], text)


def presentation_payload(value: Any) -> Any:
    """Traduce frases canónicas y añade etiquetas; preserva home/away/team y todos los identificadores."""
    if isinstance(value, list):
        return [presentation_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key.endswith("_text") or key in {"summary", "favorite", "assessment"}:
            result[key] = ([display_text(t) if isinstance(t, str) else t for t in item]
                           if isinstance(item, list) else display_text(item) if isinstance(item, str) else item)
        else:
            result[key] = presentation_payload(item)
        if key in {"home", "away", "team", "home_team", "away_team"} and isinstance(item, str):
            result[f"{key}_display"] = display_text(item)
    return result
