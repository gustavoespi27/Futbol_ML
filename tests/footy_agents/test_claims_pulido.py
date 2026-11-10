"""Frescura exige consultar cobertura; una cuota no se expresa como porcentaje."""

import pytest

from footy_agents import orchestrator, tools
from footy_agents.grounding import check_claims
from footy_agents.llm import TextDelta, ToolCall
from footy_agents.schemas import ToolCallRecord, UserPreferences


def coverage(success=True):
    return ToolCallRecord(
        tool_name="get_coverage", arguments={}, result={"stale": False}, success=success, execution_time_ms=0
    )


@pytest.mark.parametrize(
    "text",
    [
        "Los datos están actualizados.",
        "Los datos están al día.",
        "Están recién actualizados.",
        "Actualizados hasta el momento.",
    ],
)
@pytest.mark.parametrize("records,valid", [([], False), ([coverage(False)], False), ([coverage()], True)])
def test_freshness_requires_successful_coverage(text, records, valid):
    assert check_claims(text, records).verified is valid


@pytest.mark.parametrize(
    "text",
    [
        "No hay datos actualizados.",
        "Los datos no están actualizados.",
        "Sin datos actualizados no puedo responder.",
        "No puedo confirmar que los datos están actualizados.",
        "Cuota 1.53.",
        "Probabilidad de 51.6%.",
        "Cuota 1.53 con ventaja del 6%.",
        "Cuota 1.53, probabilidad de 51.6%.",
    ],
)
def test_negation_and_correct_units_still_pass(text):
    assert check_claims(text, []).verified


@pytest.mark.parametrize("text", ["Cuota esperada de más de 2.5 goles del 51.6%.", "La cuota es del 51,6 %."])
def test_percent_is_not_a_price(text):
    report = check_claims(text, [])
    assert not report.verified and "Un porcentaje es probabilidad, no cuota." in report.unverified


def test_fake_llm_consults_coverage_after_freshness_repair(monkeypatch):
    monkeypatch.setitem(tools.TOOLS_REGISTRY, "get_value_bets", lambda **_: [])
    monkeypatch.setitem(
        tools.TOOLS_REGISTRY, "get_coverage", lambda: {"stale": False, "freshness": "Datos actualizados."}
    )

    class FakeLLM:
        def __init__(self):
            self.turns = iter(
                [
                    [ToolCall("v", "get_value_bets")],
                    [TextDelta("Los datos están actualizados.")],
                    [ToolCall("c", "get_coverage")],
                    [TextDelta("Los datos están actualizados.")],
                ]
            )

        def stream_chat(self, messages, tools=None):
            yield from next(self.turns)

    events = list(orchestrator.run_chat(FakeLLM(), "¿Qué apuestas con valor hay hoy?", UserPreferences()))
    assert events[-1].data["success"]
    assert any(e.event == "step" and e.data["kind"] == "repair" for e in events)
    assert [e.data["tool"] for e in events if e.event == "tool_start"] == ["get_value_bets", "get_coverage"]
