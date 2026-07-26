"""Declarative trigger-policy regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.monitoring.triggers import (
    evaluate_row_triggers,
    load_trigger_policy,
)


def test_packaged_default_policy_is_declarative_and_stable() -> None:
    first = load_trigger_policy()
    second = load_trigger_policy()

    assert first.rules
    assert all(rule.rule_id and rule.detector_kind for rule in first.rules)
    assert first.fingerprint() == second.fingerprint()


def test_custom_policy_replaces_defaults_and_fingerprints_parameters(
    tmp_path: Path,
) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        """
schema_version: 1
lookback_turns: 0
lookahead_turns: 0
rules:
  - rule_id: slow
    event_type: latency
    source: native
    severity: critical
    detector_kind: latency_breach
    parameters:
      threshold_ms: 42
""".strip()
        + "\n",
        encoding="utf-8",
    )
    policy = load_trigger_policy(path)
    original = policy.fingerprint()

    assert [rule.rule_id for rule in policy.rules] == ["slow"]
    assert policy.lookback_turns == 0
    assert policy.lookahead_turns == 0
    assert evaluate_row_triggers(
        {"latency_ms": 43},
        policy,
        "run",
        "conversation",
        1,
    )

    path.write_text(path.read_text().replace("threshold_ms: 42", "threshold_ms: 44"))
    assert load_trigger_policy(path).fingerprint() != original


@pytest.mark.parametrize(
    "body",
    [
        "schema_version: 1\nrules: [{rule_id: bad, event_type: x, source: nope, severity: high, detector_kind: error}]\n",
        "schema_version: 1\nrules: [{rule_id: bad, event_type: x, source: native, severity: nope, detector_kind: error}]\n",
        "schema_version: 1\nrules: [{rule_id: bad, event_type: x, source: native, severity: high, detector_kind: nope}]\n",
        "schema_version: 1\nrules: [{event_type: x, source: native, severity: high, detector_kind: error}]\n",
        "schema_version: 1\nrules: [{rule_id: bad, event_type: x, source: native, severity: high, detector_kind: latency_breach, parameters: {threshold_ms: nope}}]\n",
        "schema_version: 1\nrules: [{rule_id: bad, event_type: x, source: native, severity: high, detector_kind: error, parameters: {unknown: 1}}]\n",
        "schema_version: future\nrules: [{rule_id: bad, event_type: x, source: native, severity: high, detector_kind: error}]\n",
    ],
)
def test_invalid_policy_is_rejected(tmp_path: Path, body: str) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(body)
    with pytest.raises(ContractError):
        load_trigger_policy(path)


def test_missing_custom_policy_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="trigger policy"):
        load_trigger_policy(tmp_path / "missing.yaml")


def test_agent_capture_events_are_typed_and_malformed_events_are_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = load_trigger_policy()
    triggers = evaluate_row_triggers(
        {
            "capture_events": [
                {
                    "event_type": "guardrail",
                    "severity": "high",
                    "reason": "guardrail rejected request",
                },
                {"event_type": "broken", "severity": "not-a-severity"},
            ],
            "bot_response": "normal response",
        },
        policy,
        "run",
        "conversation",
        1,
    )

    assert any(trigger.source.value == "agent" for trigger in triggers)
    assert "Ignoring malformed capture event" in caplog.text


def test_disabled_rule_does_not_fire_and_changes_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        """
schema_version: 1
agent_events_enabled: false
rules:
  - rule_id: errors
    event_type: error
    source: native
    severity: high
    detector_kind: error
    enabled: false
""".strip()
        + "\n"
    )
    policy = load_trigger_policy(path)
    assert not evaluate_row_triggers(
        {
            "capture_events": [{"event_type": "agent", "severity": "high"}],
            "bot_response": "normal response",
        },
        policy,
        "run",
        "conversation",
        1,
    )
    assert not evaluate_row_triggers(
        {
            "error": "boom",
            "capture_events": [{"event_type": "agent", "severity": "high"}],
        },
        policy,
        "run",
        "conversation",
        1,
    )

    original = policy.fingerprint()
    path.write_text(
        path.read_text().replace("    enabled: false", "    enabled: true")
    )
    enabled = load_trigger_policy(path)
    assert enabled.fingerprint() != original
    assert evaluate_row_triggers(
        {"error": "boom", "bot_response": "normal response"},
        enabled,
        "run",
        "conversation",
        1,
    )


@pytest.mark.parametrize(
    "field",
    ["agent_events_enabled", "enabled"],
)
def test_policy_boolean_fields_reject_non_booleans(
    tmp_path: Path,
    field: str,
) -> None:
    path = tmp_path / "policy.yaml"
    agent_setting = "agent_events_enabled: nope\n" if field == "agent_events_enabled" else ""
    rule_setting = "    enabled: nope\n" if field == "enabled" else ""
    path.write_text(
        (
            "schema_version: 1\n"
            f"{agent_setting}"
            "rules:\n"
            "  - rule_id: errors\n"
            "    event_type: error\n"
            "    source: native\n"
            "    severity: high\n"
            "    detector_kind: error\n"
            f"{rule_setting}"
        )
    )
    with pytest.raises(ContractError, match="boolean"):
        load_trigger_policy(path)
