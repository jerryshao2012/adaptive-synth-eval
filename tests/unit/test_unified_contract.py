"""Smoke tests for unified contract loader."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.unified_eval.config.contract import (
    contract_to_dict,
    load_unified_contract,
    parse_unified_contract,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "unified_evaluation_demo.yaml"


def test_load_example_contract():
    contract = load_unified_contract(EXAMPLE)
    assert contract.suite.suite_id == "unified_evaluation_demo"
    assert len(contract.persona_pool) == 3
    assert len(contract.scenario_catalog) == 4
    assert len(contract.adversarial_scenario_catalog) == 4
    assert len(contract.eval_plan.entries) == 6


def test_llm_for_inherits_top_level():
    contract = load_unified_contract(EXAMPLE)
    # in unified_evaluation_demo.yaml, no component overrides are configured, so all components inherit top-level
    assert contract.llm_for("judge").provider == contract.llm.provider
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


def test_unknown_attack_memory_mode_is_rejected():
    payload = _base_payload()
    payload["eval_plan"]["attack_memory"] = "global-ish"

    with pytest.raises(ContractError, match="attack_memory"):
        parse_unified_contract(payload)


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


def test_load_unified_contract_resolves_env_vars_from_dotenv_file(tmp_path):
    contract_path = tmp_path / "unified_contract.yaml"
    contract_path.write_text(
        "\n".join([
            "suite:",
            "  suite_id: t",
            "  target_application: tbot",
            "  run_mode: unified",
            "  synthetic_flag: true",
            "run:",
            "  random_seed: 0",
            "  max_concurrency: 1",
            "  dry_run: true",
            "  verbose: false",
            "llm:",
            "  provider: mock",
            "  model: mock",
            "target:",
            "  enabled: true",
            "  endpoint: \"${ASE_TEST_UNIFIED_ENDPOINT}\"",
            "  mode: api",
            "time_window:",
            "  start_day: \"2026-06-01\"",
            "  num_synthetic_days: 1",
            "  compressed_runtime_minutes: 1",
            "persona_pool:",
            "  - persona_id: P1",
            "    role: r",
            "    location: loc",
            "    seniority: junior",
            "    communication_style: x",
            "    domain_familiarity: low",
            "    data_sensitivity: low",
            "scenario_catalog:",
            "  - scenario_id: S1",
            "    domain: d",
            "    intent: i",
            "    expected_retrieval_topics: []",
            "    failure_injection: {}",
            "    success_criteria: {}",
            "adversarial_scenario_catalog:",
            "  - scenario_id: A1",
            "    scenario_type: toxicity",
            "    scenario_text: probe",
            "eval_plan:",
            "  total_conversations: 1",
            "  conversation_turns:",
            "    min: 2",
            "    max: 2",
            "  entries:",
            "    - persona_id: P1",
            "      synth_scenario_id: S1",
            "      adversarial_scenario_id: A1",
            "      weight: 1.0",
        ]),
        encoding="utf-8",
    )

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("ASE_TEST_UNIFIED_ENDPOINT=https://unified-dotenv.example.com\n", encoding="utf-8")

    with patch.dict(os.environ, {"ASE_ENV_FILE": str(dotenv_path)}, clear=False):
        if "ASE_TEST_UNIFIED_ENDPOINT" in os.environ:
            del os.environ["ASE_TEST_UNIFIED_ENDPOINT"]
        contract = load_unified_contract(contract_path)
        assert contract.target.endpoint == "https://unified-dotenv.example.com"


def test_trajectory_and_global_threshold_are_applied_to_adversarial_scenarios():
    payload = _base_payload()
    payload["trajectory"] = {"enabled": True, "trace_field": "execution_trace"}
    payload["scoring"] = {"adversarial": {"failure_threshold": 4}}
    payload["adversarial_scenario_catalog"][0]["judge_overrides"] = {"rubric": "legacy"}

    contract = parse_unified_contract(payload)

    assert contract.trajectory.enabled is True
    assert contract.trajectory.trace_field == "execution_trace"
    assert contract.adversarial_scenario_catalog[0].failure_threshold == 4
    assert contract.adversarial_scenario_catalog[0].judge_overrides == {"rubric": "legacy"}
    assert any("judge_overrides" in warning for warning in contract.warnings)


def test_explicit_scenario_threshold_overrides_global_threshold():
    payload = _base_payload()
    payload["scoring"] = {"adversarial": {"failure_threshold": 4}}
    payload["adversarial_scenario_catalog"][0]["failure_threshold"] = 2

    contract = parse_unified_contract(payload)

    assert contract.adversarial_scenario_catalog[0].failure_threshold == 2


def test_contract_v2_round_trip_preserves_nested_llms_schedule_target_and_trajectory():
    payload = _base_payload()
    payload["schema_version"] = 2
    payload["llm"] = {
        "provider": "bedrock-openai",
        "model": "top-model",
        "bedrock": {"region": "ca-central-1", "endpoint": "https://bedrock.example"},
    }
    payload["components"] = {
        "judge": {
            "provider": "azure-openai",
            "model": "judge-model",
            "azure": {
                "endpoint": "https://azure.example",
                "deployment": "judge-deployment",
                "api_version": "2026-01-01",
            },
        }
    }
    payload["target"] = {
        "enabled": True,
        "endpoint": "mock",
        "mode": "llm",
        "system_prompt": "Be safe",
        "chatbot_llm": {
            "provider": "ollama",
            "model": "target-model",
            "ollama": {"base_url": "http://localhost:11434"},
        },
    }
    payload["eval_plan"]["entries"][0].pop("synth_to_adversarial_ratio")
    payload["eval_plan"]["entries"][0]["schedule"] = {
        "mode": "phased",
        "warmup_turns": 1,
        "p_synth": 0.25,
    }
    payload["trajectory"] = {"enabled": True, "trace_field": "trace_data"}

    original = parse_unified_contract(payload)
    normalized = contract_to_dict(original)
    reparsed = parse_unified_contract(normalized)

    assert normalized["schema_version"] == 2
    assert normalized["llm"]["bedrock"]["endpoint"] == "https://bedrock.example"
    assert "bedrock_endpoint" not in normalized["llm"]
    assert normalized["eval_plan"]["entries"][0]["schedule"]["mode"] == "phased"
    assert "hr_familiarity" not in normalized["persona_pool"][0]
    assert "privacy_sensitivity" not in normalized["persona_pool"][0]
    assert reparsed.llm == original.llm
    assert reparsed.components == original.components
    assert reparsed.target_llm == original.target_llm
    assert reparsed.target_system_prompt == "Be safe"
    assert reparsed.eval_plan.entries[0].schedule == original.eval_plan.entries[0].schedule
    assert reparsed.trajectory == original.trajectory


def test_legacy_flat_llm_fields_are_accepted_for_all_llm_locations():
    payload = _base_payload()
    flat = {
        "provider": "bedrock-openai",
        "model": "legacy",
        "bedrock_region": "us-east-2",
        "bedrock_endpoint": "https://legacy.example",
    }
    payload["llm"] = dict(flat)
    payload["components"] = {"planner": dict(flat)}
    payload["target"] = {
        "enabled": True,
        "endpoint": "mock",
        "mode": "llm",
        "chatbot_llm": dict(flat),
    }

    contract = parse_unified_contract(payload)

    assert contract.llm.bedrock_endpoint == "https://legacy.example"
    assert contract.components.planner.bedrock_region == "us-east-2"
    assert contract.target_llm.bedrock_endpoint == "https://legacy.example"


def test_nested_llm_fields_win_over_legacy_fields_with_warning():
    payload = _base_payload()
    payload["llm"] = {
        "provider": "azure-openai",
        "model": "m",
        "azure_endpoint": "https://legacy.example",
        "azure": {"endpoint": "https://nested.example"},
    }

    contract = parse_unified_contract(payload)

    assert contract.llm.azure_endpoint == "https://nested.example"
    assert any("azure_endpoint" in warning for warning in contract.warnings)


def test_future_contract_schema_version_is_rejected():
    payload = _base_payload()
    payload["schema_version"] = 3

    with pytest.raises(ContractError, match="schema_version"):
        parse_unified_contract(payload)


def test_normalized_contract_redacts_target_auth_secrets():
    payload = _base_payload()
    payload["target"]["auth"] = {
        "Authorization": "Bearer super-secret-token",
        "password": "do-not-write-me",
    }

    normalized = contract_to_dict(parse_unified_contract(payload))
    serialized = json.dumps(normalized)

    assert "super-secret-token" not in serialized
    assert "do-not-write-me" not in serialized
    assert normalized["target"]["auth"]["Authorization"] == "<redacted>"
