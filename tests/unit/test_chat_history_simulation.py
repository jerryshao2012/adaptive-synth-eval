import asyncio
import json
from copy import deepcopy

from adaptive_synth_eval.config.contract import load_contract
from adaptive_synth_eval.engines.chat_history_simulation import (
    _effective_max_concurrency,
    run_simulation,
    run_simulation_async,
)


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


def test_effective_max_concurrency_is_one_for_browser_chatbot(tmp_path):
    contract_path = tmp_path / "contract.json"
    payload = {
        "simulation_suite": {
            "suite_id": "suite",
            "target_application": "hr_bot",
            "run_mode": "synthetic_chat_history_generation",
            "synthetic_flag": True,
        },
        "target_chatbot": {
            "enabled": True,
            "mode": "browser",
            "browser": {
                "url": "https://chat.example.com",
                "input_selector": "textarea",
                "submit_selector": "button",
                "response_selector": ".bot-message",
            },
        },
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
            "max_concurrency": 5,
        },
        "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run1"},
    }
    contract_path.write_text(json.dumps(payload))
    contract = load_contract(contract_path)

    assert _effective_max_concurrency(contract) == 1


def test_run_simulation_async_dry_run_writes_expected_artifacts(tmp_path):
    contract_path = tmp_path / "contract_async.json"
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
                "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run_async"},
            }
        )
    )
    contract = load_contract(contract_path)

    summary = asyncio.run(run_simulation_async(contract, dry_run=True))

    assert summary["total_conversations"] == 2
    assert (tmp_path / "outputs" / "runs" / "run_async" / "generation_report.md").exists()


def test_run_simulation_with_output_conversations(tmp_path):
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

    summary = run_simulation(contract, dry_run=True, output_conversations=True)

    assert summary["total_conversations"] == 2
    assert (tmp_path / "outputs" / "runs" / "run1" / "conversations.txt").exists()

    # Verify the file contains Persona/Bot labels
    content = (tmp_path / "outputs" / "runs" / "run1" / "conversations.txt").read_text(encoding="utf-8")
    assert "Persona (Turn 1):" in content
    assert "Bot (Turn 1):" in content
    assert "Conversation ID:" in content


def test_run_simulation_realtime_chat_display_multi_persona(tmp_path, monkeypatch):
    base_contract = {
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
            "total_conversations": 1,
            "conversation_turns": {"min": 3, "max": 3},
            "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
            "random_seed": 3,
        },
        "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run1"},
    }

    realtime_calls = []

    def _capture_realtime(*args, **kwargs):
        realtime_calls.append(kwargs)

    monkeypatch.setattr("adaptive_synth_eval.engines.chat_history_simulation.display_persona_message",
                        _capture_realtime)

    single_path = tmp_path / "single_contract.json"
    single_path.write_text(json.dumps(base_contract))
    single_contract = load_contract(single_path)
    run_simulation(single_contract, dry_run=True, realtime_chat=True)
    assert len(realtime_calls) > 0

    realtime_calls.clear()
    multi_contract_payload = deepcopy(base_contract)
    multi_contract_payload["persona_pool"].append(
        {
            "persona_id": "P002",
            "role": "manager",
            "location": "Canada",
            "seniority": "senior",
            "communication_style": "direct",
            "hr_familiarity": "high",
            "privacy_sensitivity": "medium",
        }
    )
    multi_contract_payload["output"]["run_id"] = "run2"
    multi_path = tmp_path / "multi_contract.json"
    multi_path.write_text(json.dumps(multi_contract_payload))
    multi_contract = load_contract(multi_path)
    run_simulation(multi_contract, dry_run=True, realtime_chat=True)
    assert len(realtime_calls) > 0


def test_run_simulation_realtime_can_stop_early(tmp_path, monkeypatch):
    contract_payload = {
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
            "total_conversations": 1,
            "conversation_turns": {"min": 5, "max": 5},
            "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
            "random_seed": 3,
        },
        "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run_stop"},
    }

    contract_path = tmp_path / "contract_stop.json"
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    class _FakeController:
        def __init__(self, *args, **kwargs):
            self.stop_requested = False
            self.behavior_mode = "default"
            self.active_persona_id = None

        def start(self):
            return True

        def stop(self):
            self.stop_requested = True

        def wait_if_paused(self):
            return not self.stop_requested

        def wait_for_turn_delay(self):
            # Simulate user stop right after first turn.
            self.stop_requested = True
            return False

        def set_active_persona(self, persona_id):
            self.active_persona_id = persona_id

        def get_behavior_for_persona(self, persona_id=None):
            return self.behavior_mode

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.RealtimeChatController",
        _FakeController,
    )

    summary = run_simulation(
        contract,
        dry_run=True,
        realtime_chat=True,
        interactive_realtime_controls=True,
    )

    assert summary["stopped_early"] is True
    assert summary["total_turns"] == 1


def test_realtime_controller_only_used_when_interactive_enabled(tmp_path, monkeypatch):
    contract_payload = {
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
            "total_conversations": 1,
            "conversation_turns": {"min": 3, "max": 3},
            "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
            "random_seed": 3,
        },
        "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run_non_interactive"},
    }

    contract_path = tmp_path / "contract_non_interactive.json"
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    class _ShouldNotBeCreatedController:
        def __init__(self, *args, **kwargs):
            raise AssertionError("RealtimeChatController should not be created when interactive controls are disabled")

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.RealtimeChatController",
        _ShouldNotBeCreatedController,
    )

    summary = run_simulation(
        contract,
        dry_run=True,
        realtime_chat=True,
        interactive_realtime_controls=False,
    )

    assert summary["stopped_early"] is False
    assert summary["total_turns"] == 3


def test_run_simulation_with_persona_filter(tmp_path):
    from adaptive_synth_eval.config.contract import ContractError
    import pytest

    contract_path = tmp_path / "contract_filter.json"
    contract_payload = {
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
            },
            {
                "persona_id": "P002",
                "role": "manager",
                "location": "Canada",
                "seniority": "senior",
                "communication_style": "direct",
                "hr_familiarity": "high",
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
            "total_conversations": 4,
            "conversation_turns": {"min": 3, "max": 3},
            "mix": [
                {"persona_id": "P001", "scenario_id": "S001", "weight": 0.5},
                {"persona_id": "P002", "scenario_id": "S001", "weight": 0.5}
            ],
            "random_seed": 3,
        },
        "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run_filter"},
    }
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    # 1. Run simulation filtering by P002 (case-insensitive)
    summary = run_simulation(contract, dry_run=True, persona_filter="p002")

    # Check that conversations only for P002 were run
    turns_file = tmp_path / "outputs" / "runs" / "run_filter" / "turns.jsonl"
    assert turns_file.exists()
    lines = [json.loads(line) for line in turns_file.read_text(encoding="utf-8").splitlines()]
    assert len(lines) > 0
    for turn in lines:
        assert turn["persona_id"] == "P002"

    # 2. Test invalid persona filter throws ContractError
    with pytest.raises(ContractError) as excinfo:
        run_simulation(contract, dry_run=True, persona_filter="P003")
    assert "not found in contract's persona pool" in str(excinfo.value)


def test_realtime_controller_seeded_with_filtered_persona_before_start(tmp_path, monkeypatch):
    contract_path = tmp_path / "contract_filter_realtime.json"
    contract_payload = {
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
            },
            {
                "persona_id": "P002",
                "role": "manager",
                "location": "Canada",
                "seniority": "senior",
                "communication_style": "direct",
                "hr_familiarity": "high",
                "privacy_sensitivity": "medium",
            },
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
            "mix": [
                {"persona_id": "P001", "scenario_id": "S001", "weight": 0.5},
                {"persona_id": "P002", "scenario_id": "S001", "weight": 0.5},
            ],
            "random_seed": 3,
        },
        "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "run_filter_realtime"},
    }
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    observed = {"seeded_before_start": False}

    class _FakeController:
        def __init__(self, *args, **kwargs):
            self.stop_requested = False
            self.behavior_mode = "default"
            self.active_persona_id = None

        def set_active_persona(self, persona_id):
            self.active_persona_id = persona_id

        def start(self):
            observed["seeded_before_start"] = self.active_persona_id == "P002"
            return True

        def stop(self):
            self.stop_requested = True

        def wait_if_paused(self):
            return not self.stop_requested

        def wait_for_turn_delay(self):
            return not self.stop_requested

        def get_behavior_for_persona(self, persona_id=None):
            return self.behavior_mode

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.RealtimeChatController",
        _FakeController,
    )

    run_simulation(
        contract,
        dry_run=True,
        realtime_chat=True,
        interactive_realtime_controls=True,
        persona_filter="P002",
    )

    assert observed["seeded_before_start"] is True
