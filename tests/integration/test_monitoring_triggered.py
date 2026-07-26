"""Integration coverage for production trigger-policy behavior."""

from __future__ import annotations

from adaptive_synth_eval.monitoring.triggers import (
    evaluate_row_triggers,
    load_trigger_policy,
)


def test_packaged_policy_detects_native_and_heuristic_signals() -> None:
    policy = load_trigger_policy()
    triggers = evaluate_row_triggers(
        {
            "error": "timeout",
            "latency_ms": 9000,
            "bot_response": "",
            "applied_failure_modes": ["jailbreak"],
        },
        policy,
        "run-1",
        "conversation-1",
        2,
    )

    event_types = {trigger.event_type for trigger in triggers}
    assert {
        "error",
        "latency_sla_breach",
        "response_quality_anomaly_empty",
        "applied_failure_mode_high_risk",
    }.issubset(event_types)
    assert all(trigger.rule_id for trigger in triggers)
    assert all(
        trigger.policy_fingerprint == policy.fingerprint() for trigger in triggers
    )


def test_trigger_ids_are_stable_and_rule_specific() -> None:
    policy = load_trigger_policy()
    row = {"error": "timeout", "bot_response": "normal response"}

    first = evaluate_row_triggers(row, policy, "run", "conversation", 1)
    second = evaluate_row_triggers(row, policy, "run", "conversation", 1)

    assert [trigger.trigger_id for trigger in first] == [
        trigger.trigger_id for trigger in second
    ]
    assert len({trigger.trigger_id for trigger in first}) == len(first)
