"""La evaluación distingue selección, ejecución, argumentos, respaldo y revisión manual pendiente."""

from scripts.eval_agent_routing import FALLBACK_STEP, aggregate, path_correct, percentile, turn_metrics

from footy_agents.schemas import ChatEvent


def test_action_path_needs_resolver_both_conditions_and_real_target():
    calls = [
        {"tool": "find_team", "args": {"name": "Chile"}, "success": True},
        {"tool": "create_watch", "args": {"match_id": 181043, "condition": "kickoff_soon"}, "success": True},
        {"tool": "create_watch", "args": {"match_id": 181043, "condition": "pinnacle_available"}, "success": True},
    ]
    assert path_correct("create_watch", calls, {}, None)
    assert not path_correct("create_watch", calls[1:], {}, None)
    assert not path_correct("create_watch", calls[:2], {}, None)
    calls[-1]["args"]["match_id"] = 1
    assert not path_correct("create_watch", calls, {}, None)


def test_followup_must_requery_same_entity_without_reresolving():
    call = {"tool": "analyze_match", "args": {"match_id": 181043}, "success": True}
    assert path_correct("analyze_match", [call], {"match_id": 181043}, None)
    assert not path_correct("analyze_match", [call], {"match_id": 1}, None)
    assert not path_correct("analyze_match", [call, {"tool": "get_value_bets", "args": {}, "success": True}], {}, None)
    assert not path_correct(
        "analyze_match", [call, {"tool": "find_team", "args": {}, "success": True}], {"match_id": 181043}, None
    )


def test_failed_call_is_tool_selection_but_not_a_completed_path():
    events = [
        ChatEvent(event="tool_start", data={"tool": "cancel_watch", "args": {"id": "inventado"}}),
        ChatEvent(event="tool_result", data={"tool": "cancel_watch", "success": False}),
        ChatEvent(event="step", data={"kind": "repair", "text": "Reescribir"}),
        ChatEvent(event="step", data={"kind": "repair", "text": FALLBACK_STEP}),
        ChatEvent(event="step", data={"kind": "recovery", "text": "Consultar"}),
    ]
    result = turn_metrics(events, "cancel_watch", {}, 4)
    assert result["tool_correct"] and not result["path_correct"] and not result["args_valid"]
    assert result["repairs"] == 1 and result["recoveries"] == 1 and result["fallback_used"]
    assert result["manual_interpretation"] is None


def test_cancel_id_stake_amount_and_policy_are_checked():
    cancel = [{"tool": "cancel_watch", "args": {"id": 4}, "success": True}]
    assert path_correct("cancel_watch", cancel, {}, 4)
    assert not path_correct("cancel_watch", cancel, {}, None)
    assert not path_correct("cancel_watch", cancel, {}, 5)
    stake = [{"tool": "get_stake_limits", "args": {"bankroll": 100000}, "success": True}]
    assert path_correct("get_stake_limits", stake, {}, None)
    stake[0]["args"]["bankroll"] = 1000
    assert not path_correct("get_stake_limits", stake, {}, None)
    assert path_correct("policy", [], {}, None) and not path_correct("policy", cancel, {}, None)


def test_percentiles_and_summary_do_not_claim_manual_correctness():
    assert percentile([], 50) is None
    assert percentile([7], 95) == 7
    assert percentile([30, 0, 20, 10], 50) == 15
    assert percentile([30, 0, 20, 10], 95) == 28.5
    summary = aggregate(
        [
            {
                "tool_correct": True,
                "path_correct": False,
                "elapsed_s": 3,
                "repairs": 1,
                "recoveries": 2,
                "fallback_used": True,
                "done": {"success": True},
            }
        ]
    )
    assert summary["tool_correct"] == 1 and summary["path_correct"] == 0 and summary["completed"] == 1
    assert summary["latency_p50_s"] == 3 and "Pendiente" in summary["manual_review"]
