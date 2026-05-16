import json

from adaptive_synth_eval.config.contract import load_contract
from adaptive_synth_eval.engines.chat_history_simulation import run_simulation


def test_run_simulation_dry_run_writes_expected_artifacts(tmp_path):
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
                "target_chatbot": {"enabled": False},
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
                    "total_conversations": 2,
                    "conversation_turns": {"min": 3, "max": 3},
                    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
                    "random_seed": 3,
                },
                "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run1"},
            }
        )
    )
    contract = load_contract(contract_path)

    summary = run_simulation(contract, dry_run=True)

    assert summary["total_conversations"] == 2
    assert (tmp_path / "outputs" / "runs" / "run1" / "generation_report.md").exists()
