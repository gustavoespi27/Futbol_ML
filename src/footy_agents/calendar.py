"""Calendario público local; los timestamps UTC solo se usan internamente."""

import re
from datetime import date, datetime, timedelta
from typing import Any

from footy.config import settings
from footy.web.services.context import LOCAL_TZ
from footy_agents.names import normalize_name

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
SHORT_DAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def local_fields(kickoff: str | None) -> dict[str, Any]:
    if not kickoff:
        return {"kickoff_local": None, "local_date": None, "weekday": None}
    value = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    if value.tzinfo is None:
        # Las fichas históricas también pueden traer solo una fecha, sin hora conocida.
        if len(kickoff) != 10:
            raise ValueError("El kickoff debe incluir zona horaria")
        return {"kickoff_local": None, "local_date": kickoff, "weekday": WEEKDAYS[value.weekday()]}
    local = value.astimezone(LOCAL_TZ)
    return {
        "kickoff_local": f"{SHORT_DAYS[local.weekday()]} {local:%d-%m}, {local:%H:%M} hora de Chile",
        "local_date": local.date().isoformat(),
        "weekday": WEEKDAYS[local.weekday()],
    }


def local_payload(value: Any) -> Any:
    """Barrera recursiva para resultados anidados, incluidas futuras vigilancias."""
    if isinstance(value, dict):
        result = {k: local_payload(v) for k, v in value.items() if k != "kickoff"}
        if value.get("kickoff"):
            result.update(local_fields(value["kickoff"]))
        return result
    if isinstance(value, list):
        return [local_payload(v) for v in value]
    return value


def requested_dates(day: str, today: date | None = None) -> list[date]:
    today = today or datetime.now(LOCAL_TZ).date()
    q = normalize_name(day)
    if q in {"hoy", "manana"}:
        return [today + timedelta(days=q == "manana")]
    if q in {"el finde", "finde", "fin de semana"}:
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        if today.weekday() == 6:
            return [today]
        return [saturday, saturday + timedelta(days=1)]
    days = [normalize_name(d) for d in WEEKDAYS]
    if q in days:
        return [today + timedelta(days=(days.index(q) - today.weekday()) % 7)]
    return [date.fromisoformat(day)]


def calendar_args(message: str, entities: dict | None = None) -> dict:
    q = normalize_name(message)
    args: dict = {}
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", message)
    days = ("hoy", "mañana", *WEEKDAYS, "el finde", "fin de semana")
    if iso:
        args["day"] = iso[0]
    else:
        for day in days:
            if re.search(r"\b" + normalize_name(day) + r"\b", q):
                args["day"] = day
                break
    if re.search(r"\b(?:importantes?|destacados?|destacadas?|grandes?)\b", q):
        args["important"] = True
    if re.search(r"\b(?:otros?|otras?|mas)\b", q) and entities:
        shown = entities.get("shown_ids") or ([entities["match_id"]] if entities.get("match_id") else [])
        if shown:
            args["exclude_ids"] = shown
    if "selecciones" in q:
        args["category"] = "international"
    elif re.search(r"\b(?:copas?|ligas?)\b", q):
        args["category"] = "clubs"
    return args


def competition_priority(match: dict) -> tuple:
    config = settings().get("competitions", {}).get(match.get("league"), {})
    name = normalize_name(match.get("league_name") or config.get("name", ""))
    friendly = match.get("league") == "FRIENDLY" or "amistos" in name or "friendly" in name
    return (
        int(friendly),
        config.get("odds_priority", 4),
        0 if match.get("league") in {"E0", "SP1", "D1", "I1", "F1"} else 1,
    )
