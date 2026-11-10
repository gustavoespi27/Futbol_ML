"""Identidad del asistente: presentación fija sin LLM y personalidad subordinada a las reglas."""

import pytest

from footy_agents import orchestrator, persona
from footy_agents.schemas import UserPreferences


class NoLLM:
    def stream_chat(self, messages, tools=None):
        raise AssertionError("un saludo no debe llamar al LLM")


@pytest.mark.parametrize("message", ["hola", "Hola, ¿quién eres?", "buenas tardes!", "¿qué puedes hacer?",
                                     "como te llamas", "hola míster", "Mister, ¿quién eres?",
                                     "míster", "oye mister!"])
def test_greeting_gets_fixed_intro_without_llm(message):
    out = list(orchestrator.run_chat(NoLLM(), message, UserPreferences()))
    assert [e.event for e in out] == ["step", "token", "done"]
    assert out[0].data["kind"] == "policy"
    assert out[1].data["delta"] == persona.INTRO_TEXT and persona.NAME_MID in persona.INTRO_TEXT
    assert out[2].data == {"iterations": 0, "success": True}


@pytest.mark.parametrize("message", ["hola, analiza Colombia vs Chile", "quién gana el clásico?",
                                     "hola qué partidos hay hoy", "¿qué apuestas con valor hay?"])
def test_real_questions_are_not_greetings(message):
    assert not persona.is_intro(message)


def test_vocative_is_stripped_from_real_questions():
    assert persona.without_vocative("Míster, ¿cómo llega Colo Colo?") == "¿cómo llega Colo Colo?"
    assert persona.without_vocative("¿quién gana mañana, mister?") == "¿quién gana mañana?"
    assert persona.without_vocative("analiza Mistermind FC") == "analiza Mistermind FC"
    assert not persona.is_intro("mister, analiza Colombia vs Chile")


def test_persona_leads_prompt_but_rules_win():
    prompt = orchestrator.system_prompt(UserPreferences())
    assert prompt.startswith(f"Te llamas {persona.NAME}")
    assert "Las reglas estrictas mandan sobre tu personalidad" in prompt
    assert "NUNCA inventes probabilidades" in prompt


def _analysis_record():
    from footy_agents.schemas import ToolCallRecord
    result = {"home": "Colombia", "away": "Chile", "kickoff": "2026-11-14T00:00:00Z",
              "kickoff_local": "vie 13-11, 21:00 hora de Chile",
              "probabilities": {"home": "67.5%", "draw": "20.0%", "away": "12.5%"},
              "over_2_5": "51.6%", "goals_text": "Más de 2.5 goles: 51.6% · menos de 2.5 goles: 48.4%"}
    return [ToolCallRecord(tool_name="analyze_match", arguments={}, result=result, success=True, execution_time_ms=1)]


def test_weekday_with_hour_is_not_a_day_number():
    from footy_agents.grounding import check_claims, verify_numbers
    answer = "El partido se juega este viernes a las 21:00 hora de Chile; Colombia tiene 67.5%."
    assert check_claims("Se juega este viernes 21:00 hora de Chile.", _analysis_record()).verified
    assert verify_numbers(answer, _analysis_record()).verified
    assert not verify_numbers("Se juega el viernes a las 17:00.", _analysis_record()).verified


def test_goal_line_from_market_key_is_grounded():
    from footy_agents.grounding import check_claims, verify_numbers
    good = "Más de 2.5 goles tiene 51.6% y menos de 2.5 goles, 48.4%."
    assert verify_numbers(good, _analysis_record()).verified and check_claims(good, _analysis_record()).verified
    assert not verify_numbers("Menos de 3.5 goles tiene 51.6%.", _analysis_record()).verified


def test_inverted_goal_line_is_caught():
    from footy_agents.grounding import check_claims
    report = check_claims("Probablemente termine con menos de 2.5 goles (51.6%).", _analysis_record())
    assert not report.verified and "Línea de goles invertida" in report.unverified[0]
    assert not check_claims("Habrá más de 2.5 goles con 48.4%.", _analysis_record()).verified
