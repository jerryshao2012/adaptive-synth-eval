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

    # attack_memory.json has cross-conversation entries
    am = json.loads((run_dir / "attack_memory.json").read_text())
    assert isinstance(am["entries"], list)
    assert len(am["entries"]) >= 1

    # adversarial_sessions.jsonl exists
    assert (run_dir / "adversarial_sessions.jsonl").exists()


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


def _with_output_dir(contract, base_dir: Path):
    from adaptive_synth_eval.unified_eval.config.schemas import OutputConfig
    return replace(contract, output=OutputConfig(base_dir=base_dir, run_id=contract.output.run_id))
