import json
from copy import deepcopy

import pytest


@pytest.fixture
def build_synth_contract_payload(tmp_path):
    """Build a valid synth contract payload with common defaults."""

    def _build(
        *,
        base_dir=None,
        run_id="run1",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
        random_seed=3,
        start_day="2026-05-01",
        num_synthetic_days=1,
        compressed_runtime_minutes=60,
        max_concurrency=None,
        target=None,
        persona_pool=None,
        scenario_catalog=None,
        mix=None,
        include_legacy_tool_expectations=False,
    ):
        output_base_dir = base_dir if base_dir is not None else (tmp_path / "outputs")
        personas = (
            deepcopy(persona_pool)
            if persona_pool is not None
            else [
                {
                    "persona_id": "P001",
                    "role": "new_employee",
                    "location": "Canada",
                    "seniority": "junior",
                    "communication_style": "polite",
                    "hr_familiarity": "low",
                    "privacy_sensitivity": "medium",
                }
            ]
        )
        scenarios = (
            deepcopy(scenario_catalog)
            if scenario_catalog is not None
            else [
                {
                    "scenario_id": "S001",
                    "domain": "leave",
                    "intent": "understand_eligibility",
                    "expected_retrieval_topics": ["leave"],
                    "failure_injection": {"ambiguity": 0.2},
                    "success_criteria": {"answers_grounded_in_policy": True},
                }
            ]
        )
        if include_legacy_tool_expectations:
            scenarios[0]["tool_expectations"] = {"raise_jira_ticket": "not_expected"}

        payload = {
            "simulation_suite": {
                "suite_id": "suite",
                "target_application": "hr_bot",
                "run_mode": "synthetic_chat_history_generation",
                "synthetic_flag": True,
            },
            "target": deepcopy(target) if target is not None else {"enabled": False},
            "time_window": {
                "start_day": start_day,
                "num_synthetic_days": num_synthetic_days,
                "compressed_runtime_minutes": compressed_runtime_minutes,
            },
            "persona_pool": personas,
            "scenario_catalog": scenarios,
            "traffic_orchestration": {
                "total_conversations": total_conversations,
                "conversation_turns": {"min": turn_min, "max": turn_max},
                "mix": (
                    deepcopy(mix)
                    if mix is not None
                    else [
                        {
                            "persona_id": personas[0]["persona_id"],
                            "scenario_id": scenarios[0]["scenario_id"],
                            "weight": 1.0,
                        }
                    ]
                ),
                "random_seed": random_seed,
            },
            "output": {"base_dir": str(output_base_dir), "run_id": run_id},
        }
        if max_concurrency is not None:
            payload["traffic_orchestration"]["max_concurrency"] = max_concurrency

        return payload

    return _build


@pytest.fixture
def write_synth_contract_json(tmp_path, build_synth_contract_payload):
    """Write a synth contract JSON file and return its path and payload."""

    def _write(file_name="contract.json", **build_kwargs):
        payload = build_synth_contract_payload(**build_kwargs)
        contract_path = tmp_path / file_name
        contract_path.write_text(json.dumps(payload), encoding="utf-8")
        return contract_path, payload

    return _write
