"""End-to-end dry-run: confirms both turn types are produced and persona voice flows
to the adversarial planner.
"""
from __future__ import annotations

import json
from pathlib import Path

from adaptive_synth_eval.unified_eval.config.contract import load_unified_contract
from adaptive_synth_eval.unified_eval.orchestrator.runner import run_unified

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "multi_persona_demo.yaml"


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


def _with_output_dir(contract, base_dir: Path):
    from dataclasses import replace
    from adaptive_synth_eval.unified_eval.config.schemas import OutputConfig
    return replace(contract, output=OutputConfig(base_dir=base_dir, run_id=contract.output.run_id))
