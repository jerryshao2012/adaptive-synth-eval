"""Triggered selection reconciliation, provenance, and checkpoint integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adaptive_synth_eval.monitoring import runner
from adaptive_synth_eval.artifacts.exporters import ArtifactWriter
from adaptive_synth_eval.capture.producers import ChatHistoryProducerAdapter
from adaptive_synth_eval.capture.sinks import CaptureCoordinator


def _write_history(run_dir: Path) -> None:
    rows = [
        {
            "conversation_id": "A",
            "turn_id": 1,
            "timestamp": "2026-01-01T00:00:00",
            "user_message": "one",
            "bot_response": "normal response one",
        },
        {
            "conversation_id": "A",
            "turn_id": 2,
            "timestamp": "2026-01-01T00:00:01",
            "user_message": "two",
            "bot_response": "normal response two",
            "error": "timeout",
        },
        {
            "conversation_id": "A",
            "turn_id": 3,
            "timestamp": "2026-01-01T00:00:02",
            "user_message": "three",
            "bot_response": "normal response three",
        },
    ]
    run_dir.mkdir(parents=True)
    (run_dir / "chat_history.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )


def _run(run_dir: Path, **overrides) -> dict:
    arguments = {
        "run_dir": run_dir,
        "sample_size": 2,
        "interval_minutes": 60,
        "sampling_strategy": "triggered",
        "incomplete_run_action": "resume",
        "dry_run": True,
        "max_windows": None,
        "triggered_lookback": 1,
        "triggered_lookahead": 1,
    }
    arguments.update(overrides)
    return runner.run_monitoring(**arguments)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_policy_fingerprint_reselects_without_rejudging_and_journals_provenance(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_history(run_dir)
    _run(run_dir)
    initial_scores = _jsonl(run_dir / "monitoring_scores.jsonl")
    initial_generated = {
        (row["conversation_id"], row["turn_id"]): row["value_versions"]["generated_at"]
        for row in initial_scores
    }

    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
schema_version: 1
lookback_turns: 0
lookahead_turns: 0
rules:
  - rule_id: errors-only
    event_type: error
    source: native
    severity: critical
    detector_kind: error
""".strip()
        + "\n"
    )
    _run(run_dir, trigger_policy_path=policy, sample_size=1)

    scores = _jsonl(run_dir / "monitoring_scores.jsonl")
    active = [row for row in scores if row["selected_for_monitoring"]]
    assert len(active) == 1
    assert active[0]["turn_id"] == "2"
    assert active[0]["selection_provenance"][0]["rule_id"] == "errors-only"
    assert active[0]["selection_provenance"][0]["event_type"] == "error"
    assert active[0]["selection_provenance"][0]["detector_name"] == "error"
    assert active[0]["selection_provenance"][0]["reason"]
    assert active[0]["selection_fingerprint"]
    assert active[0]["trigger_policy_fingerprint"]
    assert active[0]["selector_algorithm_version"] == "conversation-stream-v2"
    assert active[0]["value_versions"]["generated_at"] == initial_generated[("A", "2")]

    state = json.loads((run_dir / "monitoring_state.json").read_text())
    assert state["selection_fingerprint"]
    assert state["trigger_policy_fingerprint"]
    assert state["triggered_selection"]["detected_trigger_ids"]
    assert state["trigger_metrics"]["budget_drops"] >= 0

    triggers = _jsonl(run_dir / "capture" / "triggers.jsonl")
    promotions = _jsonl(run_dir / "capture" / "promotions.jsonl")
    assert len({row["trigger_id"] for row in triggers}) == len(triggers)
    assert promotions
    assert all(row["status"] == "unavailable_missing" for row in promotions)


def test_production_captured_chat_turn_is_promoted_by_stable_skeleton_id(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "captured-run"
    coordinator = CaptureCoordinator(run_dir)
    writer = ArtifactWriter(
        tmp_path,
        run_id="captured-run",
        capture_adapter=ChatHistoryProducerAdapter(coordinator),
    )
    writer.append_chat_history_rows(
        [
            {
                "conversation_id": "A",
                "turn_id": 1,
                "timestamp": "2026-01-01T00:00:00",
                "user_message": "one",
                "bot_response": "normal response one",
                "error": "timeout",
            }
        ]
    )
    coordinator.close()

    _run(
        run_dir,
        sample_size=1,
        triggered_lookback=0,
        triggered_lookahead=0,
    )

    promotions = _jsonl(run_dir / "capture" / "promotions.jsonl")
    assert promotions
    assert all(row["status"] == "promoted" for row in promotions)
    envelopes = _jsonl(run_dir / "capture" / "envelopes.jsonl")
    assert {row["envelope_id"] for row in envelopes} == {"chat-A-1"}


def test_state_write_failure_retries_window_without_duplicate_journals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    _write_history(run_dir)
    original = runner._write_monitoring_state
    calls = 0

    def fail_second_write(path: Path, state: dict) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("state checkpoint failed")
        return original(path, state)

    monkeypatch.setattr(runner, "_write_monitoring_state", fail_second_write)
    with pytest.raises(OSError, match="checkpoint"):
        _run(run_dir)

    monkeypatch.setattr(runner, "_write_monitoring_state", original)
    _run(run_dir)
    triggers = _jsonl(run_dir / "capture" / "triggers.jsonl")
    promotions = _jsonl(run_dir / "capture" / "promotions.jsonl")
    assert len({row["trigger_id"] for row in triggers}) == len(triggers)
    assert len({row["promotion_id"] for row in promotions}) == len(promotions)
    state = json.loads((run_dir / "monitoring_state.json").read_text())
    assert state["next_line_index"] == 3
