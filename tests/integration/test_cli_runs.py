import json

from adaptive_synth_eval.cli import main


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
                    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
                },
                "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run1"},
            }
        )
    )

    assert main(["run", "--contract", str(contract_path), "--dry-run"]) == 0
    assert main(["summarize", "--run-id", "run1", "--output-dir", str(tmp_path / "outputs")]) == 0


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
                "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run_unified_1"},
            }
        )
    )

    # Validate the contract
    assert main(["validate-contract", str(contract_path)]) == 0

    # Run the contract
    assert main(
        ["run", "--contract", str(contract_path), "--dry-run", "--scenario", "S1", "--adversarial-scenario", "A1"]) == 0
    assert main(["summarize", "--run-id", "run_unified_1", "--output-dir", str(tmp_path / "outputs")]) == 0


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
                    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
                },
                "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run1"},
            }
        )
    )

    # Calling with unified-only flags should return exit code 2 (ContractError)
    assert main(["run", "--contract", str(contract_path), "--dry-run", "--scenario", "S001"]) == 2
