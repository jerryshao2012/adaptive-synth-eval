import json
from pathlib import Path

from adaptive_synth_eval.cli import main
from adaptive_synth_eval.learning.experience import artifact_fingerprint
from adaptive_synth_eval.learning.models import LearningBundle
from adaptive_synth_eval.unified_eval.config.contract import (
    contract_to_dict,
    load_unified_contract,
)


def test_cli_dry_run_end_to_end(tmp_path):
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "simulation_suite": {
                    "suite_id": "suite",
                    "target_application": "hr_bot",
                    "run_mode": "synthetic_chat_history_generation",
                    "synthetic_flag": True,
                },
                "target": {"enabled": False},
                "time_window": {
                    "start_day": "2026-05-01",
                    "num_synthetic_days": 1,
                    "compressed_runtime_minutes": 60,
                },
                "persona_pool": [
                    {
                        "persona_id": "P001",
                        "role": "new_employee",
                        "location": "Canada",
                        "seniority": "junior",
                        "communication_style": "polite",
                        "hr_familiarity": "low",
                        "privacy_sensitivity": "medium",
                    }
                ],
                "scenario_catalog": [
                    {
                        "scenario_id": "S001",
                        "domain": "leave",
                        "intent": "understand_eligibility",
                        "expected_retrieval_topics": ["leave"],
                        "failure_injection": {"ambiguity": 0.2},
                        "success_criteria": {"answers_grounded_in_policy": True},
                    }
                ],
                "traffic_orchestration": {
                    "total_conversations": 1,
                    "conversation_turns": {"min": 3, "max": 3},
                    "mix": [
                        {"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}
                    ],
                },
                "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run1"},
            }
        )
    )

    assert main(["run", "--contract", str(contract_path), "--dry-run"]) == 0
    assert (
        main(
            ["summarize", "--run-id", "run1", "--output-dir", str(tmp_path / "outputs")]
        )
        == 0
    )


def test_cli_dry_run_unified_end_to_end(tmp_path):
    contract_path = tmp_path / "unified_contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "suite": {
                    "suite_id": "unified_suite",
                    "target_application": "mock_bot",
                    "run_mode": "unified",
                    "synthetic_flag": True,
                },
                "run": {
                    "random_seed": 1,
                    "max_concurrency": 1,
                    "dry_run": True,
                    "verbose": False,
                },
                "llm": {
                    "provider": "mock",
                    "model": "mock",
                },
                "target": {
                    "mode": "mock",
                    "enabled": False,
                    "endpoint": "mock",
                },
                "time_window": {
                    "start_day": "2026-06-02",
                    "num_synthetic_days": 1,
                    "compressed_runtime_minutes": 1,
                },
                "persona_pool": [
                    {
                        "persona_id": "P1",
                        "role": "tester",
                        "location": "Global",
                        "seniority": "junior",
                        "communication_style": "neutral",
                        "domain_familiarity": "low",
                        "data_sensitivity": "low",
                    }
                ],
                "scenario_catalog": [
                    {
                        "scenario_id": "S1",
                        "domain": "test",
                        "intent": "testing",
                        "expected_retrieval_topics": ["test"],
                        "failure_injection": {},
                        "success_criteria": {},
                    }
                ],
                "adversarial_scenario_catalog": [
                    {
                        "scenario_id": "A1",
                        "scenario_type": "toxicity",
                        "scenario_text": "probe toxicity",
                    }
                ],
                "eval_plan": {
                    "total_conversations": 1,
                    "conversation_turns": {"min": 2, "max": 2},
                    "entries": [
                        {
                            "persona_id": "P1",
                            "synth_scenario_id": "S1",
                            "adversarial_scenario_id": "A1",
                            "weight": 1.0,
                            "max_turns": 2,
                        }
                    ],
                },
                "output": {
                    "base_dir": str(tmp_path / "outputs"),
                    "run_id": "run_unified_1",
                },
            }
        )
    )
    bundle = LearningBundle.create(
        profile_id="demo",
        parent_id=None,
        patch=[],
        policy={"ucb_exploration_c": 2.0},
        provenance={"run_ids": ["source-run"]},
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle.to_dict()), encoding="utf-8")

    # Validate the contract
    assert main(["validate-contract", str(contract_path)]) == 0

    # Run the contract
    assert (
        main(
            [
                "run",
                "--contract",
                str(contract_path),
                "--dry-run",
                "--scenario",
                "S1",
                "--adversarial-scenario",
                "A1",
                "--learning-bundle",
                str(bundle_path),
            ]
        )
        == 0
    )
    run_dirs = list((tmp_path / "outputs" / "runs").glob("run_unified_1_*"))
    assert len(run_dirs) == 1
    normalized = json.loads(
        (run_dirs[0] / "contract.normalized.json").read_text(encoding="utf-8")
    )
    assert normalized["learning_bundle"]["digest"] == bundle.digest
    assert normalized["learning_policy"]["ucb_exploration_c"] == 2.0
    assert (
        main(
            [
                "summarize",
                "--run-id",
                run_dirs[0].name,
                "--output-dir",
                str(tmp_path / "outputs"),
            ]
        )
        == 0
    )


def test_cli_rejects_unified_flags_on_synth_contract(tmp_path):
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "simulation_suite": {
                    "suite_id": "suite",
                    "target_application": "hr_bot",
                    "run_mode": "synthetic_chat_history_generation",
                    "synthetic_flag": True,
                },
                "target": {"enabled": False},
                "time_window": {
                    "start_day": "2026-05-01",
                    "num_synthetic_days": 1,
                    "compressed_runtime_minutes": 60,
                },
                "persona_pool": [
                    {
                        "persona_id": "P001",
                        "role": "new_employee",
                        "location": "Canada",
                        "seniority": "junior",
                        "communication_style": "polite",
                        "hr_familiarity": "low",
                        "privacy_sensitivity": "medium",
                    }
                ],
                "scenario_catalog": [
                    {
                        "scenario_id": "S001",
                        "domain": "leave",
                        "intent": "understand_eligibility",
                        "expected_retrieval_topics": ["leave"],
                        "failure_injection": {"ambiguity": 0.2},
                        "success_criteria": {"answers_grounded_in_policy": True},
                    }
                ],
                "traffic_orchestration": {
                    "total_conversations": 1,
                    "conversation_turns": {"min": 3, "max": 3},
                    "mix": [
                        {"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}
                    ],
                },
                "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run1"},
            }
        )
    )

    # Calling with unified-only flags should return exit code 2 (ContractError)
    assert (
        main(
            ["run", "--contract", str(contract_path), "--dry-run", "--scenario", "S001"]
        )
        == 2
    )


def test_cli_learning_lifecycle_approve_consume_and_rollback(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    example = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "examples"
        / "unified_evaluation_demo.yaml"
    )
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "demo.yaml").write_text(
        f"""
profile_id: demo
readiness_level: L2
cadence: hourly
targets:
  - contract: {example}
learning:
  enabled: true
  min_new_runs: 1
  min_new_adversarial_conversations: 1
  validation_contracts:
    - {example}
  tournament:
    initial_pairs: 20
    batch_pairs: 20
    max_pairs: 20
""".strip(),
        encoding="utf-8",
    )
    ledger = tmp_path / "outputs" / "learning" / "demo" / "experience.jsonl"
    ledger.parent.mkdir(parents=True)

    def append_experience(run_id, angles):
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "run_id": run_id,
                        "adversarial_conversations": 100,
                        "failure_signatures": [],
                        "coverage": {
                            "personas": {"DEMO_P1": 100},
                            "scenarios": {"prompt-injection": 100},
                            "angles": angles,
                        },
                        "judge_error_rate": 0.0,
                    }
                )
                + "\n"
            )

    append_experience("source-1", {"authority_injection": 100})
    target_fingerprint = artifact_fingerprint(
        contract_to_dict(load_unified_contract(example))["target"]
    )

    def tournament_result(_self, variant, _bundle, seed, pack, _contract):
        return {
            "variant": variant,
            "seed": seed,
            "pack": pack,
            "failure_signatures": (
                ["new-reproducible-failure"]
                if variant == "challenger" and pack == "fresh"
                else []
            ),
            "detected": True,
            "judge_error": False,
            "tokens": 100,
            "coverage": {
                "personas": "DEMO_P1",
                "scenarios": "prompt-injection",
                "angles": "authority_injection",
            },
            "target_fingerprint": target_fingerprint,
        }

    monkeypatch.setattr(
        "adaptive_synth_eval.learning.coordinator.EvaluatorTournamentExecutor.__call__",
        tournament_result,
    )

    common = [
        "--profile",
        "demo",
        "--profiles-dir",
        str(profiles),
        "--output-dir",
        "outputs",
    ]
    assert main(["learn", "run", *common]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "candidate_passed"

    assert (
        main(
            [
                "learn",
                "approve",
                *common,
                "--candidate",
                first["candidate_id"],
                "--actor",
                "reviewer",
                "--reason",
                "first validated version",
            ]
        )
        == 0
    )
    capsys.readouterr()

    consumed = {}

    def execute_contract_run(**kwargs):
        consumed["bundle"] = kwargs["learning_bundle"]
        return {"run_id": "explicit-learning-run"}

    monkeypatch.setattr(
        "adaptive_synth_eval.cli._execute_contract_run",
        execute_contract_run,
    )
    bundle_path = (
        tmp_path
        / "outputs"
        / "learning"
        / "demo"
        / "candidates"
        / first["candidate_id"]
        / "bundle.json"
    )
    assert (
        main(
            [
                "run",
                "--contract",
                str(example),
                "--learning-bundle",
                str(bundle_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert consumed["bundle"].bundle_id == first["bundle_id"]

    append_experience(
        "source-2",
        {"authority_injection": 50, "role_entrapment": 50},
    )
    assert main(["learn", "run", *common]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "candidate_passed"
    assert (
        main(
            [
                "learn",
                "approve",
                *common,
                "--candidate",
                second["candidate_id"],
                "--actor",
                "reviewer",
                "--reason",
                "second validated version",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "learn",
                "rollback",
                *common,
                "--to",
                first["bundle_id"],
                "--actor",
                "reviewer",
                "--reason",
                "regression detected",
            ]
        )
        == 0
    )
    rollback = json.loads(capsys.readouterr().out)
    assert rollback["bundle_id"] == first["bundle_id"]
