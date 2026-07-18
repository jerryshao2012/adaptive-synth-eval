"""End-to-end dry-run: confirms both turn types are produced and persona voice flows
to the adversarial planner.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.unified_eval.config.contract import load_unified_contract
from adaptive_synth_eval.unified_eval.orchestrator.runner import run_unified

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "unified_evaluation_demo.yaml"


def test_dry_run_produces_mixed_turns_and_artifacts(tmp_path: Path):
    contract = load_unified_contract(EXAMPLE)
    # Redirect output_dir to tmp; preserve everything else.
    contract = _with_output_dir(contract, tmp_path)
    summary = run_unified(contract, dry_run=True, run_id_override="orchestrator_test")

    run_dir = tmp_path / "runs" / "orchestrator_test"
    assert run_dir.exists()
    assert summary["total_turns"] > 0
    assert summary["synth_turns"] > 0
    assert summary["adversarial_turns"] > 0

    # turns.jsonl has both turn_types
    turn_types = {
        json.loads(line)["turn_type"]
        for line in (run_dir / "turns.jsonl").read_text().splitlines()
        if line.strip()
    }
    assert turn_types == {"synth", "adversarial"}

    # scores.jsonl rows tagged correctly
    score_rows = [
        json.loads(line)
        for line in (run_dir / "scores.jsonl").read_text().splitlines()
        if line.strip()
    ]
    synth_rows = [r for r in score_rows if r["turn_type"] == "synth"]
    adv_rows = [r for r in score_rows if r["turn_type"] == "adversarial"]
    assert synth_rows and adv_rows
    # synth rows have safety_score; adv rows have failure_score
    assert any(r.get("safety_score") is not None for r in synth_rows)
    assert any(r.get("failure_score") is not None for r in adv_rows)
    assert all({
                   "best_failure_score",
                   "effective_failure_score",
                   "best_effective_failure_score",
                   "failure_threshold",
                   "is_breach",
                   "confidence",
                   "reasoning",
                   "judge_error",
               } <= row.keys() for row in adv_rows)

    adversarial_turns = [
        json.loads(line)
        for line in (run_dir / "turns.jsonl").read_text().splitlines()
        if line.strip() and json.loads(line).get("turn_type") == "adversarial"
    ]
    assert all("effective_failure_score" in row for row in adversarial_turns)

    conversation_rows = [
        json.loads(line)
        for line in (run_dir / "conversations.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert all({
                   "best_effective_failure_score", "failure_threshold", "is_breach"
               } <= row.keys() for row in conversation_rows)
    assert summary["failure_percentiles"]["failure_score"]["count"] == len(adv_rows)

    # attack_memory.json has cross-conversation entries
    am = json.loads((run_dir / "attack_memory.json").read_text())
    assert isinstance(am["entries"], list)
    assert len(am["entries"]) >= 1
    assert all("effective_failure_score" in entry for entry in am["entries"])

    # adversarial_sessions.jsonl exists
    assert (run_dir / "adversarial_sessions.jsonl").exists()
    sessions = [
        json.loads(line)
        for line in (run_dir / "adversarial_sessions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert all({
                   "best_failure_score", "best_effective_failure_score",
                   "failure_threshold", "is_breach",
               } <= session.keys() for session in sessions)
    assert all({
                   "failure_score", "best_failure_score", "effective_failure_score",
                   "best_effective_failure_score", "failure_threshold", "is_breach",
               } <= turn.keys() for session in sessions for turn in session["turns"])

    run_state = json.loads((run_dir / "run_state.json").read_text())
    assert run_state["version"] == 2
    assert len(run_state["contract_fingerprint"]) == 64
    assert len(run_state["plan_fingerprint"]) == 64
    assert "meter" in run_state and "attack_memory" in run_state
    assert "reserved_tokens" not in json.dumps(run_state["meter"])

    normalized = json.loads((run_dir / "contract.normalized.json").read_text())
    run_plan = json.loads((run_dir / "run_plan.json").read_text())
    assert normalized["schema_version"] == 2
    assert all("schedule" in row for row in run_plan)


def test_unified_persona_filter_is_case_insensitive(tmp_path: Path):
    contract = load_unified_contract(EXAMPLE)
    contract = _with_output_dir(contract, tmp_path)

    summary = run_unified(
        contract,
        dry_run=True,
        run_id_override="orchestrator_case_insensitive",
        persona_filter="demo_p1",
    )

    assert summary["total_conversations"] > 0
    run_dir = tmp_path / "runs" / "orchestrator_case_insensitive"
    convo_rows = [
        json.loads(line)
        for line in (run_dir / "conversations.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert convo_rows
    assert {row["persona_id"] for row in convo_rows} == {"DEMO_P1"}


def test_per_persona_attack_memory_is_persisted_in_isolated_buckets(tmp_path: Path):
    contract = load_unified_contract(EXAMPLE)
    contract = replace(
        _with_output_dir(contract, tmp_path),
        eval_plan=replace(contract.eval_plan, attack_memory="per_persona"),
    )

    run_unified(contract, dry_run=True, run_id_override="per_persona_memory")
    memory = json.loads(
        (tmp_path / "runs" / "per_persona_memory" / "attack_memory.json").read_text()
    )

    assert memory["mode"] == "per_persona"
    assert len(memory["personas"]) >= 2
    for persona_id, bucket in memory["personas"].items():
        assert all(
            entry["session_id"].startswith("conv_") for entry in bucket["entries"]
        ), persona_id


def test_unified_persona_filter_raises_for_unknown_persona(tmp_path: Path):
    contract = load_unified_contract(EXAMPLE)
    contract = _with_output_dir(contract, tmp_path)

    with pytest.raises(ContractError, match="Specified persona 'DOES_NOT_EXIST' not found"):
        run_unified(
            contract,
            dry_run=True,
            run_id_override="orchestrator_invalid_persona",
            persona_filter="DOES_NOT_EXIST",
        )


def test_effective_concurrency_reports_requested_value(tmp_path: Path):
    contract = load_unified_contract(EXAMPLE)
    contract = replace(_with_output_dir(contract, tmp_path), run=replace(contract.run, max_concurrency=16))

    summary = run_unified(contract, dry_run=True, run_id_override="orchestrator_concurrency")

    assert summary["configured_max_concurrency"] == 16
    assert summary["effective_max_concurrency"] == 16


def test_concurrent_budget_admission_does_not_persist_zero_turn_conversations(tmp_path: Path):
    contract = load_unified_contract(EXAMPLE)
    contract = replace(
        _with_output_dir(contract, tmp_path),
        run=replace(contract.run, budget=1_500, reserve_tokens=1_500, max_concurrency=8),
    )

    summary = run_unified(contract, dry_run=True, run_id_override="bounded_budget")
    rows = [
        json.loads(line)
        for line in (tmp_path / "runs" / "bounded_budget" / "conversations.jsonl").read_text().splitlines()
        if line.strip()
    ]

    assert summary["budget"]["stopped_due_to_budget"] is True
    assert summary["total_conversations"] < summary["planned_conversations"]
    assert all(row["turn_count"] > 0 for row in rows)


def test_v2_resume_restores_usage_memory_and_skips_completed_conversations(tmp_path: Path):
    contract = _with_output_dir(load_unified_contract(EXAMPLE), tmp_path)
    first = run_unified(contract, dry_run=True, run_id_override="resume_v2")
    run_dir = tmp_path / "runs" / "resume_v2"
    before_rows = (run_dir / "conversations.jsonl").read_text().splitlines()
    before_memory = json.loads((run_dir / "attack_memory.json").read_text())

    resumed = run_unified(
        contract,
        dry_run=True,
        run_id_override="resume_v2",
        resume_incomplete=True,
    )

    after_rows = (run_dir / "conversations.jsonl").read_text().splitlines()
    after_memory = json.loads((run_dir / "attack_memory.json").read_text())
    assert resumed["budget"]["used_total_tokens"] == first["budget"]["used_total_tokens"]
    assert after_rows == before_rows
    assert len(after_memory["entries"]) == len(before_memory["entries"])


def test_enabled_trajectory_with_empty_target_trace_skips_summarizer_call(tmp_path: Path):
    from adaptive_synth_eval.config.schemas import ConversationTurns
    from adaptive_synth_eval.unified_eval.config.schemas import Schedule, TrajectoryConfig

    contract = _with_output_dir(load_unified_contract(EXAMPLE), tmp_path)
    entry = replace(contract.eval_plan.entries[0], schedule=Schedule(mode="phased", warmup_turns=0))
    contract = replace(
        contract,
        trajectory=TrajectoryConfig(enabled=True),
        eval_plan=replace(
            contract.eval_plan,
            total_conversations=1,
            conversation_turns=ConversationTurns(min=2, max=2),
            entries=[entry],
        ),
    )

    summary = run_unified(contract, dry_run=True, run_id_override="empty_trace")
    components = {
        row["component"]: row for row in summary["budget"]["per_component"]
    }

    assert summary["adversarial_turns"] == 2
    assert components["judge"]["calls"] == 2
    assert summary["trajectory"]["sessions_with_signal"] == 0


def test_run_logs_startup_conversation_batch(tmp_path: Path, caplog):
    contract = load_unified_contract(EXAMPLE)
    contract = replace(_with_output_dir(contract, tmp_path), run=replace(contract.run, max_concurrency=4))

    with caplog.at_level("INFO"):
        run_unified(contract, dry_run=True, run_id_override="orchestrator_startup_log")

    assert "Starting " in caplog.text
    assert "max_concurrency=4" in caplog.text
    assert "already completed=0, skipped=0" in caplog.text


def test_realtime_persona_filter_runs_single_conversation(tmp_path: Path):
    contract = load_unified_contract(EXAMPLE)
    contract = replace(_with_output_dir(contract, tmp_path), run=replace(contract.run, max_concurrency=16))

    summary = run_unified(
        contract,
        dry_run=True,
        run_id_override="orchestrator_realtime_persona_single",
        realtime_chat=True,
        interactive_realtime_controls=False,
        persona_filter="DEMO_P1",
    )

    assert summary["total_conversations"] == 1
    assert summary["configured_max_concurrency"] == 16
    assert summary["effective_max_concurrency"] == 1


def test_realtime_run_emits_progress_sink_updates(tmp_path: Path):
    contract = load_unified_contract(EXAMPLE)
    contract = replace(_with_output_dir(contract, tmp_path), run=replace(contract.run, max_concurrency=2))

    updates = []

    def _sink(payload):
        updates.append(dict(payload))

    summary = run_unified(
        contract,
        dry_run=True,
        run_id_override="orchestrator_realtime_progress_sink",
        realtime_chat=True,
        interactive_realtime_controls=False,
        persona_filter="DEMO_P1",
        progress_sink=_sink,
    )

    assert summary["total_conversations"] == 1
    assert updates
    assert updates[0]["completed"] == 0
    assert any((u.get("completed") or 0) >= 1 for u in updates)


def test_round_robin_plan_by_persona_interleaves_order():
    from adaptive_synth_eval.unified_eval.orchestrator.runner import _round_robin_plan_by_persona

    plan = [
        {"persona_id": "P1", "conversation_key": "k1"},
        {"persona_id": "P1", "conversation_key": "k2"},
        {"persona_id": "P1", "conversation_key": "k3"},
        {"persona_id": "P2", "conversation_key": "k4"},
        {"persona_id": "P2", "conversation_key": "k5"},
        {"persona_id": "P3", "conversation_key": "k6"},
    ]
    interleaved = _round_robin_plan_by_persona(plan, ["P1", "P2", "P3"])

    assert [p["persona_id"] for p in interleaved[:4]] == ["P1", "P2", "P3", "P1"]


def test_estimate_remaining_seconds_returns_expected_value():
    from adaptive_synth_eval.unified_eval.orchestrator.runner import _estimate_remaining_seconds

    eta = _estimate_remaining_seconds(completed=10, total=50, elapsed_seconds=20.0)

    assert eta == pytest.approx(80.0)


def test_estimate_remaining_seconds_handles_unknown_or_empty_progress():
    from adaptive_synth_eval.unified_eval.orchestrator.runner import _estimate_remaining_seconds

    assert _estimate_remaining_seconds(completed=0, total=50, elapsed_seconds=20.0) is None
    assert _estimate_remaining_seconds(completed=10, total=None, elapsed_seconds=20.0) is None


def test_resume_fingerprints_are_stable_and_reject_changed_plan():
    from adaptive_synth_eval.unified_eval.orchestrator.runner import (
        _fingerprint_payload,
        _validate_resume_fingerprints,
    )

    contract_fingerprint = _fingerprint_payload({"b": 2, "a": 1})
    assert contract_fingerprint == _fingerprint_payload({"a": 1, "b": 2})
    state = {
        "version": 2,
        "contract_fingerprint": contract_fingerprint,
        "plan_fingerprint": _fingerprint_payload([{"conversation_id": "conv_000001"}]),
    }

    with pytest.raises(ContractError, match="run plan"):
        _validate_resume_fingerprints(
            state,
            contract_fingerprint=contract_fingerprint,
            plan_fingerprint=_fingerprint_payload([{"conversation_id": "conv_000002"}]),
        )


def test_future_run_state_version_is_rejected():
    from adaptive_synth_eval.unified_eval.orchestrator.runner import (
        _validate_resume_fingerprints,
    )

    with pytest.raises(ContractError, match="run-state version"):
        _validate_resume_fingerprints(
            {"version": 3}, contract_fingerprint="a", plan_fingerprint="b"
        )


@pytest.mark.asyncio
async def test_sliding_window_bounds_concurrency_and_stops_new_admission():
    import asyncio

    from adaptive_synth_eval.unified_eval.orchestrator.runner import _run_sliding_window

    started: list[int] = []
    active = 0
    peak = 0

    async def worker(item: int) -> None:
        nonlocal active, peak
        started.append(item)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1

    await _run_sliding_window(
        list(range(10)),
        worker=worker,
        max_concurrency=3,
        can_admit=lambda: len(started) < 4,
    )

    assert peak <= 3
    assert len(started) < 10


def _with_output_dir(contract, base_dir: Path):
    from adaptive_synth_eval.unified_eval.config.schemas import OutputConfig
    return replace(contract, output=OutputConfig(base_dir=base_dir, run_id=contract.output.run_id))
