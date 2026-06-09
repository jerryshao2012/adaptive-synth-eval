"""Smoke tests for unified contract loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.unified_eval.config.contract import (
    load_unified_contract,
    parse_unified_contract,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "unified_evaluation_demo.yaml"


def test_load_example_contract():
    contract = load_unified_contract(EXAMPLE)
    assert contract.suite.suite_id == "multi_persona_demo_suite"
    assert len(contract.persona_pool) == 3
    assert len(contract.scenario_catalog) == 4
    assert len(contract.adversarial_scenario_catalog) == 4
    assert len(contract.eval_plan.entries) == 6


def test_llm_for_inherits_top_level():
    contract = load_unified_contract(EXAMPLE)
    # in unified_evaluation_demo.yaml, no component overrides are configured, so all components inherit top-level
    assert contract.llm_for("judge").provider == "bedrock"
    assert contract.llm_for("planner").provider == contract.llm.provider


def test_unknown_persona_id_rejected():
    payload = _base_payload()
    payload["eval_plan"]["entries"][0]["persona_id"] = "P_NOPE"
    with pytest.raises(ContractError):
        parse_unified_contract(payload)


def test_unknown_adversarial_id_rejected():
    payload = _base_payload()
    payload["eval_plan"]["entries"][0]["adversarial_scenario_id"] = "A_NOPE"
    with pytest.raises(ContractError):
        parse_unified_contract(payload)


def test_ratio_out_of_range_rejected():
    payload = _base_payload()
    payload["eval_plan"]["entries"][0]["synth_to_adversarial_ratio"] = 1.5
    with pytest.raises(ContractError):
        parse_unified_contract(payload)


def test_trajectory_defaults_disabled_when_block_omitted():
    contract = parse_unified_contract(_base_payload())
    assert contract.trajectory.enabled is False
    assert contract.trajectory.trace_field == "trace"


def test_trajectory_enabled_from_contract_yaml():
    payload = _base_payload()
    payload["trajectory"] = {"enabled": True, "trace_field": "exec_trace"}
    contract = parse_unified_contract(payload)
    assert contract.trajectory.enabled is True
    assert contract.trajectory.trace_field == "exec_trace"


def _base_payload() -> dict:
    return {
        "suite": {"suite_id": "t", "target_application": "tbot", "run_mode": "unified", "synthetic_flag": True},
        "run": {"random_seed": 0, "max_concurrency": 1, "dry_run": True, "verbose": False},
        "llm": {"provider": "mock", "model": "mock"},
        "target": {"enabled": False, "endpoint": "mock", "mode": "api"},
        "time_window": {"start_day": "2026-06-01", "num_synthetic_days": 1, "compressed_runtime_minutes": 1},
        "persona_pool": [{
            "persona_id": "P1", "role": "r", "location": "loc", "seniority": "junior",
            "communication_style": "x", "domain_familiarity": "low", "data_sensitivity": "low",
        }],
        "scenario_catalog": [{
            "scenario_id": "S1", "domain": "d", "intent": "i",
            "expected_retrieval_topics": [], "failure_injection": {}, "success_criteria": {},
        }],
        "adversarial_scenario_catalog": [{
            "scenario_id": "A1", "scenario_type": "toxicity", "scenario_text": "probe",
        }],
        "eval_plan": {
            "total_conversations": 1,
            "conversation_turns": {"min": 2, "max": 2},
            "entries": [{
                "persona_id": "P1", "synth_scenario_id": "S1", "adversarial_scenario_id": "A1",
                "weight": 1.0, "synth_to_adversarial_ratio": 0.5, "max_turns": 2,
            }],
        },
    }


def test_adversarial_scenarios_parsed_from_scenario_catalog():
    payload = _base_payload()
    # Omit adversarial_scenario_catalog
    payload.pop("adversarial_scenario_catalog")
    # Define adversarial fields in scenario_catalog scenario
    payload["scenario_catalog"][0]["scenario_type"] = "toxicity"
    payload["scenario_catalog"][0]["scenario_text"] = "inline probe"
    # Update eval plan to point adversarial entry to S1
    payload["eval_plan"]["entries"][0]["adversarial_scenario_id"] = "S1"

    contract = parse_unified_contract(payload)
    assert len(contract.scenario_catalog) == 1
    assert len(contract.adversarial_scenario_catalog) == 1
    assert contract.adversarial_scenario_catalog[0].scenario_id == "S1"
    assert contract.adversarial_scenario_catalog[0].scenario_type == "toxicity"
    assert contract.adversarial_scenario_catalog[0].scenario_text == "inline probe"
