import json
import os
from unittest.mock import patch

import pytest

from adaptive_synth_eval.config.contract import ContractError, contract_to_dict, load_contract
from adaptive_synth_eval.config.schemas import FailureInjection, Scenario


def _base_contract(tmp_path):
    return {
        "simulation_suite": {
            "suite_id": "suite",
            "target_application": "hr_bot",
            "run_mode": "synthetic_chat_history_generation",
            "synthetic_flag": True,
        },
        "target": {"enabled": False},
        "time_window": {
            "start_day": "2026-05-01",
            "num_synthetic_days": 7,
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
                "tool_expectations": {"raise_jira_ticket": "not_expected"},
            }
        ],
        "traffic_orchestration": {
            "total_conversations": 4,
            "conversation_turns": {"min": 3, "max": 8},
            "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
        },
        "output": {"base_dir": str(tmp_path)},
    }


def test_load_contract_normalizes_defaults_and_warns_for_legacy_tools(tmp_path):
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(_base_contract(tmp_path)))

    contract = load_contract(path)

    assert contract.synthetic_flag is True
    assert contract.output.base_dir == tmp_path
    assert contract.traffic.conversation_turns.min == 3
    assert any("tool_expectations" in warning for warning in contract.warnings)


def test_load_contract_parses_optional_scenario_reference_answer(tmp_path):
    payload = _base_contract(tmp_path)
    payload["scenario_catalog"][0]["context"] = "Employees qualify after 90 days."
    payload["scenario_catalog"][0]["reference_answer"] = (
        "Eligibility begins after 90 days of employment."
    )
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    contract = load_contract(path)
    scenario = contract.scenario_catalog[0]

    assert scenario.context == "Employees qualify after 90 days."
    assert scenario.reference_answer == "Eligibility begins after 90 days of employment."


def test_scenario_reference_answer_does_not_shift_extended_positional_arguments():
    scenario = Scenario(
        "S001", None, None, [], FailureInjection(), {}, "context", "adversarial",
    )

    assert scenario.scenario_type == "adversarial"
    assert scenario.reference_answer is None


def test_load_contract_rejects_missing_persona_required_field(tmp_path):
    payload = _base_contract(tmp_path)
    del payload["persona_pool"][0]["privacy_sensitivity"]
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ContractError, match="privacy_sensitivity"):
        load_contract(path)


def test_load_contract_rejects_invalid_turn_range(tmp_path):
    payload = _base_contract(tmp_path)
    payload["traffic_orchestration"]["conversation_turns"] = {"min": 1, "max": 12}
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ContractError, match="3-8"):
        load_contract(path)


def test_load_contract_resolves_env_vars_in_endpoint(tmp_path):
    """Test that environment variables in contract are resolved."""
    payload = _base_contract(tmp_path)
    payload["target"] = {
        "enabled": True,
        "endpoint": "${CHATBOT_ENDPOINT:-https://default.example.com}",
        "timeout_seconds": 30.0,
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    # Test with env var set
    with patch.dict(os.environ, {"CHATBOT_ENDPOINT": "http://custom-endpoint:8080"}):
        contract = load_contract(path)
        assert contract.target.endpoint == "http://custom-endpoint:8080"

    # Test with env var not set (should use default)
    with patch.dict(os.environ, {}, clear=False):
        if "CHATBOT_ENDPOINT" in os.environ:
            del os.environ["CHATBOT_ENDPOINT"]
        contract = load_contract(path)
        assert contract.target.endpoint == "https://default.example.com"


def test_load_contract_resolves_env_vars_without_default(tmp_path):
    """Test that environment variables without defaults resolve to empty string when not set."""
    payload = _base_contract(tmp_path)
    payload["target"] = {
        "enabled": True,
        "endpoint": "${CUSTOM_ENDPOINT}",
        "timeout_seconds": 30.0,
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    # Test with env var set
    with patch.dict(os.environ, {"CUSTOM_ENDPOINT": "http://my-endpoint"}):
        contract = load_contract(path)
        assert contract.target.endpoint == "http://my-endpoint"

    # Test with env var not set (should be empty string)
    with patch.dict(os.environ, {}, clear=False):
        if "CUSTOM_ENDPOINT" in os.environ:
            del os.environ["CUSTOM_ENDPOINT"]
        contract = load_contract(path)
        assert contract.target.endpoint == ""


def test_load_contract_resolves_env_vars_from_dotenv_file(tmp_path):
    payload = _base_contract(tmp_path)
    payload["target"] = {
        "enabled": True,
        "endpoint": "${ASE_TEST_CHATBOT_ENDPOINT}",
        "timeout_seconds": 30.0,
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(payload))

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("ASE_TEST_CHATBOT_ENDPOINT=https://dotenv.example.com\n", encoding="utf-8")

    with patch.dict(os.environ, {"ASE_ENV_FILE": str(dotenv_path)}, clear=False):
        if "ASE_TEST_CHATBOT_ENDPOINT" in os.environ:
            del os.environ["ASE_TEST_CHATBOT_ENDPOINT"]
        contract = load_contract(contract_path)
        assert contract.target.endpoint == "https://dotenv.example.com"


def test_load_contract_parses_simulator_llm_config(tmp_path):
    payload = _base_contract(tmp_path)
    payload["llm"] = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "max_tokens": 2048,
        "temperature": 0.2,
        "api_key_env": "OPENAI_API_KEY",
        "azure": {
            "endpoint": "https://example.azure.com",
            "deployment": "my-deployment",
            "api_version": "2024-12-01-preview",
        },
        "bedrock": {
            "region": "us-east-1",
            "endpoint": "https://bedrock-mantle.us-east-1.api.aws/v1",
        },
        "ollama": {
            "base_url": "http://localhost:11434",
        },
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    contract = load_contract(path)

    assert contract.llm.provider == "openai"
    assert contract.llm.model == "gpt-4o-mini"
    assert contract.llm.max_tokens == 2048
    assert contract.llm.temperature == 0.2
    assert contract.llm.api_key_env == "OPENAI_API_KEY"
    assert contract.llm.azure_endpoint == "https://example.azure.com"
    assert contract.llm.azure_deployment == "my-deployment"
    assert contract.llm.azure_api_version == "2024-12-01-preview"
    assert contract.llm.bedrock_region == "us-east-1"
    assert contract.llm.bedrock_endpoint == "https://bedrock-mantle.us-east-1.api.aws/v1"
    assert contract.llm.ollama_base_url == "http://localhost:11434"


def test_load_contract_resolves_env_vars_in_simulator_llm_config(tmp_path):
    payload = _base_contract(tmp_path)
    payload["llm"] = {
        "provider": "${SIM_PROVIDER:-openai}",
        "model": "${SIM_MODEL:-gpt-4o-mini}",
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    with patch.dict(os.environ, {"SIM_PROVIDER": "anthropic", "SIM_MODEL": "claude-sonnet-4"}, clear=False):
        contract = load_contract(path)
        assert contract.llm.provider == "anthropic"
        assert contract.llm.model == "claude-sonnet-4"


def test_load_contract_parses_browser_chatbot_config(tmp_path):
    payload = _base_contract(tmp_path)
    payload["target"] = {
        "enabled": True,
        "mode": "browser",
        "browser": {
            "browser_type": "edge",
            "url": "https://chat.example.com",
            "input_selector": "textarea",
            "submit_selector": "button[type='submit']",
            "response_selector": ".bot-message",
            "ready_selector": ".chat-ready",
            "response_timeout_seconds": 45.0,
            "headless": True,
        },
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    contract = load_contract(path)

    assert contract.target.mode == "browser"
    assert contract.target.browser is not None
    assert contract.target.browser.browser_type == "edge"
    assert contract.target.browser.url == "https://chat.example.com"
    assert contract.target.browser.input_selector == "textarea"
    assert contract.target.browser.submit_selector == "button[type='submit']"
    assert contract.target.browser.response_selector == ".bot-message"
    assert contract.target.browser.ready_selector == ".chat-ready"
    assert contract.target.browser.response_timeout_seconds == 45.0
    assert contract.target.browser.headless is True


def test_contract_to_dict_serializes_browser_chatbot_config(tmp_path):
    payload = _base_contract(tmp_path)
    payload["target"] = {
        "enabled": True,
        "mode": "browser",
        "browser": {
            "url": "https://chat.example.com",
            "input_selector": "textarea",
            "submit_selector": "button",
            "response_selector": ".bot-message",
        },
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)

    serialized = contract_to_dict(contract)

    assert serialized["target"]["browser"]["url"] == "https://chat.example.com"


def test_load_contract_parses_agentcore_target_config(tmp_path):
    payload = _base_contract(tmp_path)
    payload["target"] = {
        "enabled": True,
        "mode": "agentcore",
        "agentcore": {
            "region": "us-east-1",
            "agent_runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:123:runtime/r1",
            "qualifier": "DEFAULT",
            "payload_prompt_key": "prompt",
            "runtime_session_id_prefix": "ase_tfsa_",
        },
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    contract = load_contract(path)

    assert contract.target.mode == "agentcore"
    assert contract.target.agentcore is not None
    assert contract.target.agentcore.region == "us-east-1"
    assert contract.target.agentcore.agent_runtime_arn.endswith("runtime/r1")


def test_contract_to_dict_serializes_agentcore_target_config(tmp_path):
    payload = _base_contract(tmp_path)
    payload["target"] = {
        "enabled": True,
        "mode": "agentcore",
        "agentcore": {
            "region": "us-east-1",
            "agent_runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:123:runtime/r1",
            "payload_prompt_key": "prompt",
            "runtime_session_id_prefix": "ase_tfsa_",
        },
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)

    serialized = contract_to_dict(contract)

    assert serialized["target"]["agentcore"]["region"] == "us-east-1"
    assert serialized["target"]["agentcore"]["runtime_session_id_prefix"] == "ase_tfsa_"
