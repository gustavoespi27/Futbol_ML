"""Ojeador determinista: precios ofrecidos ESPN; nunca una referencia alternativa a Pinnacle."""

import logging
import math
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def american_to_decimal(text: str | int | float) -> float:
    """Convierte una cuota americana finita, distinta de cero, sin inferir precios ausentes."""
    if isinstance(text, bool):
        raise ValueError("Cuota americana inválida")
    try:
        value = float(str(text).strip().replace("−", "-"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Cuota americana inválida") from exc
    if not math.isfinite(value) or value == 0:
        raise ValueError("Cuota americana no finita o cero")
    price = round(1 + (value / 100 if value > 0 else 100 / abs(value)), 3)
    if price <= 1:
        raise ValueError("Precio decimal debe superar uno")
    return price


def _moneyline(offer: dict, side: str) -> Any:
    value = (offer.get("moneyline") or {}).get(side) or {}
    for stage in ("close", "open"):
        odds = (value.get(stage) or {}).get("odds")
        if odds is not None:
            return odds
    if side == "draw":
        return (offer.get("drawOdds") or {}).get("moneyLine")
    return None


def parse_event_odds(event: dict, now: datetime | None = None, rejected: list[str] | None = None) -> list[dict]:
    """Filas sin match_id: act lo asigna exclusivamente mediante match_sources, nunca por nombres."""
    now = now or datetime.now(timezone.utc)
    reasons = rejected if rejected is not None else []
    rows: list[dict] = []
    competitions = event.get("competitions") or []
    if not competitions or not isinstance(competitions[0], dict):
        reasons.append("Evento sin competición")
        return rows
    if event.get("date"):
        try:
            kickoff = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            if kickoff.tzinfo is None or kickoff <= now:
                reasons.append("Evento iniciado o fecha sin zona")
                return rows
        except (TypeError, ValueError):
            reasons.append("Fecha de evento inválida")
            return rows
    for offer in competitions[0].get("odds") or []:
        if not isinstance(offer, dict):
            reasons.append("Oferta ausente")
            continue
        book = (offer.get("provider") or {}).get("name")
        if not isinstance(book, str) or not book.strip():
            reasons.append("Oferta sin proveedor")
            continue
        base = {
            "source": "espn_odds",
            "bookmaker": book.strip(),
            "captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "is_closing": 0,
        }
        try:
            prices = [american_to_decimal(_moneyline(offer, side)) for side in ("home", "draw", "away")]
            margin = sum(1 / price for price in prices)
            if not 1 <= margin <= 1.25:
                raise ValueError(f"Margen 1X2 fuera de rango: {margin:.4f}")
            rows.extend(
                {**base, "market": "1X2", "line": 0, "selection": selection, "price": price}
                for selection, price in zip(("H", "D", "A"), prices)
            )
        except (ValueError, TypeError, AttributeError) as exc:
            reasons.append(f"{book}: 1X2 descartado: {exc}")
        try:
            line = float(offer["overUnder"])
            totals = offer.get("total") or {}
            prices = []
            for side, key in (("over", "overOdds"), ("under", "underOdds")):
                stages = totals.get(side) or {}
                stage = stages.get("close") or stages.get("open") or {}
                if stage.get("line") and float(str(stage["line"]).lstrip("ou")) != line:
                    raise ValueError("Líneas OU distintas")
                prices.append(american_to_decimal(stage.get("odds", offer.get(key))))
            over, under = prices
            if not math.isfinite(line) or line <= 0:
                raise ValueError("Línea OU inválida")
            rows.extend(
                {**base, "market": "OU", "line": line, "selection": selection, "price": price}
                for selection, price in (("OVER", over), ("UNDER", under))
            )
        except (KeyError, ValueError, TypeError):
            reasons.append(f"{book}: OU sin línea y ambos precios válidos")
    for reason in reasons:
        log.debug("Evento %s: %s", event.get("id"), reason)
    return rows
