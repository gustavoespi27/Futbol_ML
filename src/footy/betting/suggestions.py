"""Apuestas sugeridas: selecciones con la mejor relación riesgo/recompensa según el sistema.

Regla fijada ANTES de mirar resultados (ver docs/decisiones.md, 2026-10-09):
  - recompensa: valor esperado EV = p × cuota − 1 >= MIN_EV;
  - riesgo: cuota entre MIN_ODDS y MAX_ODDS (las cuotas largas son las que más pierden, análisis 01) y p >= MIN_P;
  - solo cuotas reales de una casa (no estimadas) y una selección por partido.
Se ordenan por crecimiento esperado del bankroll (criterio de Kelly), que pondera a la vez cuánto se gana y con
qué probabilidad se pierde. El monto sugerido es una fracción de Kelly con tope.

Esto NO es una ventaja demostrada: el sistema iguala al mercado pero no lo supera. Las sugerencias se registran
antes de cada partido para medir su resultado real (footy.prediction.tracking).
"""

from itertools import combinations

import numpy as np

MIN_EV = 0.03
MIN_ODDS = 1.30
MAX_ODDS = 4.0
MIN_P = 0.25
KELLY_FRACTION = 0.25
MAX_STAKE = 0.025          # nunca más de 2,5% del bankroll en una apuesta
RULES = {"min_ev": MIN_EV, "min_odds": MIN_ODDS, "max_odds": MAX_ODDS, "min_p": MIN_P,
         "kelly_fraction": KELLY_FRACTION, "max_stake": MAX_STAKE}


def stake_fraction(p: float, odds: float) -> float:
    """Fracción del bankroll: KELLY_FRACTION × Kelly, con tope MAX_STAKE; 0 si no hay valor."""
    if odds <= 1:
        return 0.0
    kelly = (p * odds - 1) / (odds - 1)
    return float(min(max(kelly, 0.0) * KELLY_FRACTION, MAX_STAKE))


def growth(p: float, odds: float, f: float | None = None) -> float:
    """Crecimiento logarítmico esperado del bankroll apostando la fracción f (por defecto stake_fraction)."""
    f = stake_fraction(p, odds) if f is None else f
    if f <= 0:
        return 0.0
    return float(p * np.log1p(f * (odds - 1)) + (1 - p) * np.log1p(-f))


def risk_level(p: float) -> str:
    return "bajo" if p >= 0.60 else "medio" if p >= 0.45 else "alto"


def qualifies(p: float, odds: float | None) -> bool:
    return odds is not None and MIN_ODDS <= odds <= MAX_ODDS and p >= MIN_P and p * odds - 1 >= MIN_EV


def pick_singles(candidates: list[dict]) -> list[dict]:
    """candidates: dicts con match (id), key, p, odds (+ lo que se quiera arrastrar).
    Devuelve una selección por partido (la de mayor crecimiento) que cumple la regla, ordenadas de mejor a peor."""
    best: dict = {}
    for c in candidates:
        if c.get("estimated") or not qualifies(c["p"], c.get("odds")):
            continue
        g = growth(c["p"], c["odds"])
        if c["match"] not in best or g > best[c["match"]]["growth"]:
            best[c["match"]] = {**c, "ev": c["p"] * c["odds"] - 1, "stake": stake_fraction(c["p"], c["odds"]),
                                "growth": g, "risk": risk_level(c["p"])}
    return sorted(best.values(), key=lambda s: -s["growth"])


def pick_doubles(singles: list[dict], top: int = 3, pool: int = 6) -> list[dict]:
    """Dobles entre las mejores simples (partidos distintos). La combinada multiplica probabilidades y cuotas."""
    out = []
    for a, b in combinations(singles[:pool], 2):
        p, odds = a["p"] * b["p"], a["odds"] * b["odds"]
        out.append({"legs": [a, b], "p": p, "odds": odds, "ev": p * odds - 1,
                    "stake": stake_fraction(p, odds), "growth": growth(p, odds), "risk": risk_level(p)})
    return sorted(out, key=lambda d: -d["growth"])[:top]
