"""Stateful triggered-selection tests."""

from __future__ import annotations

from adaptive_synth_eval.monitoring.selection import (
    TriggeredSelectionState,
    select_triggered_window,
)
from adaptive_synth_eval.monitoring.triggers import load_trigger_policy


def _row(conversation: str, turn: int, *, error: str | None = None) -> dict:
    return {
        "conversation_id": conversation,
        "turn_id": turn,
        "bot_response": f"normal response {conversation}-{turn}",
        "error": error,
    }


def test_interleaved_conversations_never_share_context() -> None:
    result = select_triggered_window(
        [
            (0, _row("A", 1)),
            (1, _row("B", 1)),
            (2, _row("A", 2, error="boom")),
            (3, _row("B", 2)),
            (4, _row("A", 3)),
        ],
        state=TriggeredSelectionState(),
        policy=load_trigger_policy(),
        run_id="run",
        lookback=1,
        lookahead=1,
        budget=10,
    )

    assert [(row["conversation_id"], row["turn_id"]) for _, row in result.rows] == [
        ("A", 1),
        ("A", 2),
        ("A", 3),
    ]


def test_lookback_crosses_windows_and_pending_lookahead_resumes() -> None:
    rows_by_line = {
        0: _row("A", 1),
        1: _row("A", 2, error="boom"),
        2: _row("A", 3),
    }
    resolver = lambda locator: rows_by_line.get(locator.line_index)
    first = select_triggered_window(
        [(0, rows_by_line[0])],
        state=TriggeredSelectionState(),
        policy=load_trigger_policy(),
        run_id="run",
        lookback=1,
        lookahead=1,
        budget=10,
        row_resolver=resolver,
    )
    second = select_triggered_window(
        [(1, rows_by_line[1])],
        state=first.state,
        policy=load_trigger_policy(),
        run_id="run",
        lookback=1,
        lookahead=1,
        budget=10,
        row_resolver=resolver,
    )
    restored = TriggeredSelectionState.from_dict(second.state.to_dict())
    third = select_triggered_window(
        [(2, rows_by_line[2])],
        state=restored,
        policy=load_trigger_policy(),
        run_id="run",
        lookback=1,
        lookahead=1,
        budget=10,
        row_resolver=resolver,
    )

    assert [line for line, _ in second.rows] == [0, 1]
    assert [line for line, _ in third.rows] == [2]
    assert third.metrics["pending_lookahead"] == 0


def test_lookahead_distance_counts_same_conversation_turns() -> None:
    result = select_triggered_window(
        [
            (0, _row("A", 1, error="boom")),
            (1, _row("B", 1)),
            (2, _row("B", 2)),
            (3, _row("A", 2)),
        ],
        state=TriggeredSelectionState(),
        policy=load_trigger_policy(),
        run_id="run",
        lookback=0,
        lookahead=1,
        budget=10,
    )

    association = next(
        item
        for item in result.provenance[3]
        if item["role"] == "after" and item["event_type"] == "error"
    )
    assert association["distance"] == 1
    assert association["detector_name"] == "error"
    assert association["reason"]


def test_budget_is_hard_and_trigger_rows_rank_before_context() -> None:
    result = select_triggered_window(
        [
            (0, _row("A", 1)),
            (1, _row("A", 2, error="high")),
            (2, _row("A", 3)),
            (3, _row("B", 1, error="high")),
        ],
        state=TriggeredSelectionState(),
        policy=load_trigger_policy(),
        run_id="run",
        lookback=1,
        lookahead=1,
        budget=2,
    )

    assert len(result.rows) == 2
    assert {line for line, _ in result.rows} == {1, 3}
    assert result.metrics["budget_drops"] >= 1
    assert all(
        any(association["role"] == "trigger" for association in result.provenance[line])
        for line, _ in result.rows
    )


def test_equal_distance_context_ranks_before_then_source_line() -> None:
    result = select_triggered_window(
        [
            (0, _row("A", 1)),
            (1, _row("A", 2, error="boom")),
            (2, _row("A", 3)),
        ],
        state=TriggeredSelectionState(),
        policy=load_trigger_policy(),
        run_id="run",
        lookback=1,
        lookahead=1,
        budget=2,
    )

    assert [line for line, _ in result.rows] == [0, 1]


def test_context_severity_does_not_upgrade_trigger_priority(tmp_path) -> None:
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """
schema_version: 1
rules:
  - rule_id: low-error
    event_type: error
    source: native
    severity: low
    detector_kind: error
  - rule_id: critical-latency
    event_type: latency
    source: native
    severity: critical
    detector_kind: latency_breach
    parameters: {threshold_ms: 100}
""".strip()
        + "\n"
    )
    critical_context = _row("A", 1)
    critical_context["latency_ms"] = 200
    low_trigger_with_critical_context = _row("A", 2, error="boom")
    critical_trigger = _row("B", 1)
    critical_trigger["latency_ms"] = 200
    result = select_triggered_window(
        [
            (0, critical_context),
            (1, low_trigger_with_critical_context),
            (2, critical_trigger),
        ],
        state=TriggeredSelectionState(),
        policy=load_trigger_policy(policy_path),
        run_id="run",
        lookback=1,
        lookahead=1,
        budget=2,
    )

    assert {line for line, _ in result.rows} == {0, 2}


def test_state_serializes_only_recent_locators() -> None:
    result = select_triggered_window(
        [(0, _row("A", 1))],
        state=TriggeredSelectionState(),
        policy=load_trigger_policy(),
        run_id="run",
        lookback=1,
        lookahead=0,
        budget=10,
    )
    snapshot = result.state.recent_by_conversation["A"][0]
    assert set(snapshot) == {"locator"}
    assert "bot_response" not in str(result.state.to_dict())


def test_legacy_empty_state_payload_is_compatible() -> None:
    state = TriggeredSelectionState.from_dict({"detected_trigger_ids": ["old"]})
    assert state.detected_trigger_ids == ["old"]
    assert state.pending == []
