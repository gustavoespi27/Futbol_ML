"""El apostador profesional: apostar contra el precio de la casa "sharp", no contra un modelo propio.

Cómo trabaja un profesional del value betting (y cómo lo hace este módulo):
1. Precio justo: las cuotas de Pinnacle (la casa más eficiente, la que aceptan los profesionales) sin su margen.
   Sin Pinnacle NO se apuesta: en el histórico, otras referencias (Betfair, promedio) no dieron CLV positivo.
2. Line shopping: entre las casas "blandas" disponibles se toma la que paga más por cada resultado.
3. Valor: se apuesta solo si cuota_blanda × p_justa − 1 ≥ MIN_EDGE, con cuota ≤ MAX_ODDS y en 1X2 (el mercado
   validado). Una apuesta por partido: la de mayor crecimiento esperado.
4. Monto: ¼ de Kelly con p_justa, máximo MAX_STAKE del bankroll por apuesta y MAX_DAILY de exposición por día.
5. Se mide con CLV: cuota tomada × p_justa al cierre − 1. CLV positivo sostenido es la prueba de ventaja.

Regla elegida con 2013-2021 en 22 ligas (football-data, cuotas tempranas vs cierre) y probada en 2022-2026:
ver scripts/pro_backtest.py y docs/analisis/06_profesional.md.
"""

import numpy as np

from footy.betting.suggestions import growth, risk_level

SHARP = "Pinnacle"
# Casas donde no se "apuesta" en la simulación: la referencia, exchanges (precio neto distinto) y agregados.
NOT_PLAYABLE = {"Pinnacle", "Betfair Exchange", "Betfair", "Market Max", "Market Avg", "Tu casa"}
MIN_EDGE = 0.06
MAX_ODDS = 4.0
KELLY_FRACTION = 0.25
MAX_STAKE = 0.02
MAX_DAILY = 0.10
RULES = {"sharp": SHARP, "min_edge": MIN_EDGE, "max_odds": MAX_ODDS, "kelly_fraction": KELLY_FRACTION,
         "max_stake": MAX_STAKE, "max_daily": MAX_DAILY, "market": "1X2"}
SEL = ("H", "D", "A")
KEYS = {"H": "1", "D": "X", "A": "2"}


def fair_1x2(odds_1x2: dict[str, dict]) -> np.ndarray | None:
    """Probabilidades justas desde Pinnacle (margen repartido proporcionalmente), o None si no hay Pinnacle."""
    pin = odds_1x2.get(SHARP)
    if not pin or not all(s in pin and pin[s] > 1 for s in SEL):
        return None
    inv = np.array([1 / pin[s] for s in SEL])
    return inv / inv.sum()


def best_prices(odds_1x2: dict[str, dict]) -> dict[str, tuple[float, str]]:
    """Mejor cuota disponible por resultado entre las casas jugables: {sel: (cuota, casa)}."""
    best: dict[str, tuple[float, str]] = {}
    for book, d in odds_1x2.items():
        if book in NOT_PLAYABLE:
            continue
        for s in SEL:
            if s in d and d[s] > 1 and (s not in best or d[s] > best[s][0]):
                best[s] = (float(d[s]), book)
    return best


def stake(p: float, odds: float) -> float:
    if odds <= 1:
        return 0.0
    kelly = (p * odds - 1) / (odds - 1)
    return float(min(max(kelly, 0.0) * KELLY_FRACTION, MAX_STAKE))


def evaluate(odds_1x2: dict[str, dict]) -> list[dict]:
    """Todas las selecciones 1X2 de un partido con precio justo, mejor cuota, ventaja y si cumplen la regla."""
    p = fair_1x2(odds_1x2)
    if p is None:
        return []
    best = best_prices(odds_1x2)
    out = []
    for i, s in enumerate(SEL):
        if s not in best:
            continue
        o, book = best[s]
        edge = float(p[i] * o - 1)
        ok = edge >= MIN_EDGE and o <= MAX_ODDS
        out.append({"key": KEYS[s], "sel": s, "p_fair": float(p[i]), "fair_odds": float(1 / p[i]),
                    "pinnacle": float(odds_1x2[SHARP][s]), "odds": o, "book": book, "edge": edge,
                    "bet": ok, "stake": stake(p[i], o) if ok else 0.0,
                    "growth": growth(p[i], o, stake(p[i], o)) if ok else 0.0, "risk": risk_level(p[i])})
    return out


def pick(match_opps: dict[int, list[dict]]) -> list[dict]:
    """Una apuesta por partido (la de mayor crecimiento), ordenadas de mejor a peor y con tope diario de exposición."""
    picks = []
    for mid, opps in match_opps.items():
        ok = [o for o in opps if o["bet"]]
        if ok:
            picks.append({**max(ok, key=lambda o: o["growth"]), "match": mid})
    picks.sort(key=lambda o: -o["growth"])
    total, out = 0.0, []
    for p in picks:
        s = min(p["stake"], max(MAX_DAILY - total, 0.0))
        if s <= 0:
            break
        out.append({**p, "stake": s})
        total += s
    return out


def clv(odds_taken: float, closing_1x2: dict[str, dict], sel: str) -> float | None:
    """CLV contra el precio justo de Pinnacle al cierre (o su último snapshot antes del partido)."""
    p = fair_1x2(closing_1x2)
    return None if p is None else float(odds_taken * p[SEL.index(sel)] - 1)
