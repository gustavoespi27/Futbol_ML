"""Verificación numérica superficial: procedencia de cifras, no veracidad semántica de afirmaciones."""

import re
from typing import Any

from footy.betting import pro
from footy_agents.schemas import AgentSchema, ToolCallRecord

DATE_TIME = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z?)?|\b\d{1,2}:\d{2}(?::\d{2})?")
NUMBER = re.compile(r"(?<!\w)[+−-]?\d+(?:[.,]\d+)*\s*%?(?!\w)")


class GroundingReport(AgentSchema):
    verified: bool
    unverified: list[str]


def _numbers(text: str) -> list[tuple[str, float, float]]:
    out = []
    text = text.replace("¼", "0.25")
    text = re.sub(r"(?<!\d)1\s*/\s*4(?!\d)", "0.25", text)
    text = DATE_TIME.sub("", text)
    for match in NUMBER.finditer(text):
        raw = match.group().strip()
        normalized = raw.replace("−", "-").replace(" ", "")
        currency = text[max(0, match.start() - 1):match.start()] == "$" or bool(
            re.match(r"\s*(?:pesos|CLP)\b", text[match.end():], re.I))
        if (currency or normalized.count(".") > 1) and re.fullmatch(
                r"[+-]?[1-9]\d{0,2}(?:\.\d{3})+(?:,\d+)?", normalized):
            normalized = normalized.replace(".", "")
        normalized = normalized.replace(",", ".")
        percent = normalized.endswith("%")
        value = normalized.rstrip("%")
        digits = len(value.split(".")[1]) if "." in value else 0
        scale = 0.01 if percent else 1.0
        # Cubre el redondeo de porcentajes: -0.0303 respalda -3,0%.
        tolerance = max(1e-9, 0.5 * 10 ** -digits * scale) if digits or percent else 1e-9
        try:
            parsed = float(value) * scale
        except ValueError:
            parsed = float("nan")  # cifra mal formada: nunca se verifica, pero no interrumpe el SSE
        out.append((raw, parsed, tolerance))
    return out


def _values(value: Any) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        # Una fecha narrada («1 de enero de 2099») puede respaldarse con la fecha ISO de la herramienta.
        dates = [float(n) for match in DATE_TIME.finditer(value) for n in re.findall(r"\d+", match.group())]
        return [n for _, n, _ in _numbers(value)] + dates
    if isinstance(value, dict):
        return [n for child in value.values() for n in _values(child)]
    if isinstance(value, (list, tuple)):
        return [n for child in value for n in _values(child)]
    return []


def verify_numbers(answer: str, records: list[ToolCallRecord], user_message: str = "") -> GroundingReport:
    known = [n for record in records if record.success for n in _values(record.result)]
    known.extend([pro.KELLY_FRACTION, pro.MAX_STAKE, pro.MAX_DAILY, pro.MIN_EDGE])
    known.extend(value for _, value, _ in _numbers(user_message))
    missing = list(dict.fromkeys(raw for raw, value, tolerance in _numbers(answer)
                                if not any(abs(value - candidate) <= tolerance + 1e-12 for candidate in known)))
    return GroundingReport(verified=not missing, unverified=missing)
