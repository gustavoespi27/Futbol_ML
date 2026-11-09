"""Cifras fieles, redondeo porcentual y exclusión de fechas y horas."""

import pytest

from footy_agents.grounding import verify_numbers
from footy_agents.llm import TextDelta
from footy_agents.orchestrator import run_chat
from footy_agents.schemas import ToolCallRecord, UserPreferences


def record(result, success=True):
    return ToolCallRecord(tool_name="datos", arguments={}, result=result, success=success, execution_time_ms=0)


@pytest.mark.parametrize("answer,data,verified", [
    ("CLV −3,0% y 60 apuestas", {"clv": -0.0303, "n": 60}, True),
    ("Probabilidad 53,2%", {"p": "53.2%"}, True),
    ("CLV +3,0%", {"clv": -0.0303}, False),
    ("Hay 99 apuestas", {"n": 60}, False),
    ("El 2026-11-08 a las 12:30", {}, True),
    ("Cuota 2,10", {"odds": 2.1}, True),
    ("54 partidos", {"p": 0.54}, False),
    ("Hay 1 partido", {"flag": True}, False),
    ("Probabilidades 1X2 y liga E0", {}, True),
    ("El 1 de enero de 2099", {"kickoff": "2099-01-01T18:00:00Z"}, True),
    ("El 1 de enero de 2029", {"kickoff": "2099-01-01T18:00:00Z"}, False),
])
def test_numeric_grounding(answer, data, verified):
    assert verify_numbers(answer, [record(data)]).verified is verified


def test_failed_tools_do_not_support_claims():
    assert verify_numbers("99 partidos", [record({"n": 99}, False)]).unverified == ["99"]


def test_unsupported_answer_uses_existing_error_contract():
    class Invented:
        def stream_chat(self, *_):
            yield TextDelta("La cuota es 9,99.")
    events = list(run_chat(Invented(), "hola", UserPreferences()))
    assert [e.event for e in events] == ["token", "error", "done"]
    assert events[-1].data["success"] is False
