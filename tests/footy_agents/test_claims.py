"""Interpretaciones conocidas: frases calculadas y reparación antes de emitir texto."""

import sqlite3

import pytest

from footy_agents import orchestrator, tools
from footy_agents.grounding import check_claims
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.schemas import ToolCallRecord, UserPreferences

FORM = {"team": "Colo Colo", "last5_counts": {"won": 2, "drawn": 2, "lost": 1},
        "form_text": "En sus últimos 5 partidos ganó 2, empató 2 y perdió 1 (EEPGG, más antiguo a la izquierda)."}


def record(name, result):
    return ToolCallRecord(tool_name=name, arguments={}, result=result, success=True, execution_time_ms=0)


@pytest.mark.parametrize("text,bad", [
    ("Tope diario: 2 % de la banca.", True), ("Tope por apuesta: 10 %.", True),
    ("Máximo de 2% por día.", True), ("El 10% es por apuesta.", True),
    ("Tope por apuesta: 2 %. Tope diario: 10 %.", False),
    ("Tope por apuesta: $2.000 (2 %). Tope diario: $10.000 (10 %).", False),
    ("Ganó 3, empató 2 y perdió 1.", True), ("Empatado 2 y ganado 3.", True),
    ("Ganado 2, empatado 1, perdido 2.", True), (FORM["form_text"], False),
])
def test_counts_and_limits(text, bad):
    assert check_claims(text, [record("get_team_form", FORM)]).verified is not bad


@pytest.mark.parametrize("clv,text,bad", [
    (-.03, "CLV negativo: señal favorable.", True),
    (-.03, "CLV -3,0%: se ganó al precio de cierre.", True),
    (-.03, "El CLV es ganador.", True),
    (-.03, "CLV negativo: señal desfavorable.", False),
    (-.03, "El CLV no es favorable.", False),
    (.03, "CLV positivo: señal desfavorable.", True),
    (.03, "CLV: se tomó peor precio.", True),
    (.03, "CLV positivo: señal favorable.", False),
    (0, "CLV neutro.", False),
])
def test_clv_polarity(clv, text, bad):
    assert check_claims(text, [record("get_system_performance", {"tracking": {"bets_clv": clv}})]).verified is not bad


@pytest.mark.parametrize("clv,yield_,official,market", [(-.03, -.074, .98, .96), (.03, .1, .9, 1), (0, 0, 1, 1)])
def test_assessment_and_canonical_limits(clv, yield_, official, market):
    tracking = {"bets_clv": clv, "bets_yield": yield_, "hit_rate": .518,
                "ll_official": official, "ll_market": market}
    text = tools.performance_assessment(tracking)
    assert check_claims(text, [record("get_system_performance", {"tracking": tracking})]).verified
    assert ("el mercado es mejor" if market < official else "el pronóstico oficial es mejor" if official < market
            else "ambos son iguales") in text
    limits = tools.tool_get_stake_limits(100000)
    assert limits["limits_text"] == ("Tope por apuesta: $2.000 (2 % de la banca). "
                                     "Tope diario: $10.000 (10 % de la banca). Son topes, no una apuesta sugerida.")
    assert check_claims(limits["limits_text"], []).verified
    assert "sin datos" in tools.performance_assessment({})


def test_team_form_canonical_text(monkeypatch):
    def database():
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE teams (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO teams VALUES (1, 'Colo Colo')")
        return conn
    monkeypatch.setattr(tools, "connect", database)
    recent = [{"outcome": outcome, "date": "2026-11-01", "opponent": "Rival", "is_home": True,
               "score": [0, 0]} for outcome in "DD LWW".replace(" ", "")]
    profile = {"name": "Colo Colo", "recent": recent}
    monkeypatch.setattr(tools.service, "team_profile", lambda _: profile)
    result = tools.tool_get_team_form("Colo Colo")
    assert result["form_text"] == FORM["form_text"]
    assert result["last5_counts"] == FORM["last5_counts"]
    profile["recent"] = []
    assert "No hay partidos" in tools.tool_get_team_form("Colo Colo")["form_text"]


@pytest.mark.parametrize("name,args,result,bad,good", [
    ("get_team_form", {"team": "Colo Colo"}, FORM, "Ganó 3, empató 2 y perdió 1.", FORM["form_text"]),
    ("get_stake_limits", {"bankroll": 100000}, tools.tool_get_stake_limits(100000),
     "El tope diario es 2 %.", tools.tool_get_stake_limits(100000)["limits_text"]),
    ("get_stake_limits", {"bankroll": 100000}, tools.tool_get_stake_limits(100000),
     "El tope por apuesta es 10 %.", tools.tool_get_stake_limits(100000)["limits_text"]),
    ("get_system_performance", {}, {"tracking": {"bets_clv": -.03}},
     "El CLV negativo es favorable.", "El CLV negativo es desfavorable."),
    ("get_system_performance", {}, {"tracking": {"bets_clv": .03}},
     "El CLV positivo es desfavorable.", "El CLV positivo es favorable."),
])
def test_semantic_confusion_repairs_before_emitting(monkeypatch, name, args, result, bad, good):
    monkeypatch.setattr(orchestrator, "upcoming_focus", lambda _: None)
    monkeypatch.setitem(tools.TOOLS_REGISTRY, name, lambda **kwargs: result)

    class FakeLLM:
        def __init__(self):
            self.turns = iter([[ToolCall("a", name, args)], [TextDelta(bad)], [TextDelta(good)]])
            self.messages = []

        def stream_chat(self, messages, tools=None):
            self.messages.append([dict(m) for m in messages])
            yield from next(self.turns)

    client = FakeLLM()
    events = list(orchestrator.run_chat(client, "Consulta los datos", UserPreferences()))
    assert "".join(e.data["delta"] for e in events if e.event == "token") == good
    assert sum(e.event == "step" and e.data["kind"] == "repair" for e in events) == 1
    assert "Copia literalmente" in client.messages[-1][-1]["content"]
    assert events[-1].data["success"]
