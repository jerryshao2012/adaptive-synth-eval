from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from adaptive_synth_eval.learning.experience import (
    ExperienceBuilder,
    artifact_fingerprint,
)


def _write_run(
    root,
    run_id: str,
    *,
    dry_run: bool = False,
    synthetic_flag: bool = True,
    corrupt_fingerprint: bool = False,
):
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    contract = {
        "suite": {"suite_id": "demo", "synthetic_flag": synthetic_flag},
        "target": {"mode": "dry_run", "endpoint": "target-v1"},
        "persona_pool": [{"persona_id": "P1"}],
        "scenario_catalog": [],
        "adversarial_scenario_catalog": [
            {
                "scenario_id": "ADV1",
                "scenario_type": "prompt-injection",
                "scenario_text": "test",
            }
        ],
        "eval_plan": {"recipes": [{"recipe_id": "R1", "weight": 1}]},
    }
    plan = [{"conversation_id": "conv-1", "seed": 11}]
    contract_fingerprint = artifact_fingerprint(contract)
    if corrupt_fingerprint:
        contract_fingerprint = "not-the-contract"
    (run_dir / "contract.normalized.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )
    (run_dir / "run_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (run_dir / "run_state.json").write_text(
        json.dumps(
            {
                "version": 2,
                "mode": "unified",
                "status": "completed",
                "run_id": run_id,
                "contract_fingerprint": contract_fingerprint,
                "plan_fingerprint": artifact_fingerprint(plan),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "dry_run": dry_run,
                "total_conversations": 1,
                "adversarial_turns": 1,
                "tokens": {"total_tokens": 120},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "conversations.jsonl").write_text(
        json.dumps(
            {
                "conversation_id": "conv-1",
                "persona_id": "P1",
                "adversarial_scenario_id": "ADV1",
                "is_breach": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "turns.jsonl").write_text(
        json.dumps(
            {
                "conversation_id": "conv-1",
                "turn_id": 1,
                "persona_id": "P1",
                "turn_type": "adversarial",
                "synthetic_flag": synthetic_flag,
                "generation_metadata": {
                    "adversarial_scenario_id": "ADV1",
                    "strategy": {
                        "attack_angle": "authority",
                        "sub_tactic": "  Executive   override ",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "scores.jsonl").write_text(
        json.dumps(
            {
                "conversation_id": "conv-1",
                "turn_id": 1,
                "turn_type": "adversarial",
                "failure_type": "instruction-bypass",
                "is_breach": True,
                "judge_error": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def test_experience_builder_mines_structural_failure_and_deduplicates(tmp_path):
    run_dir = _write_run(tmp_path, "run-1")
    builder = ExperienceBuilder(tmp_path, "profile")

    first = builder.mine([run_dir])
    second = builder.mine([run_dir])

    assert first["added"] == 1
    assert second["added"] == 0
    record = first["records"][0]
    assert record["run_id"] == "run-1"
    assert record["adversarial_conversations"] == 1
    assert record["target_fingerprint"]
    assert record["failure_signatures"][0]["seed"] == 11
    assert (
        record["failure_signatures"][0]["components"]["scenario_type"]
        == "prompt-injection"
    )
    assert record["failure_signatures"][0]["components"] == {
        "target_fingerprint": record["target_fingerprint"],
        "scenario_type": "prompt-injection",
        "failure_type": "instruction-bypass",
        "attack_angle": "authority",
        "sub_tactic": "executive override",
    }
    assert record["coverage"]["personas"] == {"P1": 1}
    assert record["coverage"]["scenarios"] == {"prompt-injection": 1}
    assert record["coverage"]["angles"] == {"authority": 1}
    assert record["tokens_per_conversation"] == 120.0


def test_experience_builder_skips_ineligible_or_tampered_runs(tmp_path):
    dry = _write_run(tmp_path, "dry", dry_run=True)
    real = _write_run(tmp_path, "real-data", synthetic_flag=False)
    tampered = _write_run(tmp_path, "tampered", corrupt_fingerprint=True)
    builder = ExperienceBuilder(tmp_path, "profile")

    result = builder.mine([dry, real, tampered])

    assert result["added"] == 0
    reasons = {item["run_id"]: item["reason"] for item in result["skipped"]}
    assert reasons["dry"] == "dry_run"
    assert reasons["real-data"] == "non_synthetic"
    assert reasons["tampered"] == "contract_fingerprint_mismatch"


def test_experience_builder_serializes_concurrent_deduplication(tmp_path):
    run_dir = _write_run(tmp_path, "run-1")

    def mine_once():
        return ExperienceBuilder(tmp_path, "profile").mine([run_dir])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: mine_once(), range(8)))

    records = ExperienceBuilder(tmp_path, "profile").read_records()
    assert sum(result["added"] for result in results) == 1
    assert [record["run_id"] for record in records] == ["run-1"]
