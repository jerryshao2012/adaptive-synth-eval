import json
import os
from unittest.mock import patch

import pytest
from adaptive_synth_eval.config.contract import ContractError, contract_to_dict, load_contract


def _base_contract(tmp_path):
    return {
        "simulation_suite": {
            "suite_id": "suite",
            "target_application": "hr_bot",
            "run_mode": "synthetic_chat_history_generation",
            "synthetic_flag": True,
        },
        "target_chatbot": {"enabled": False},
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
    payload["target_chatbot"] = {
        "enabled": True,
        "endpoint": "${CHATBOT_ENDPOINT:-https://default.example.com}",
        "timeout_seconds": 30.0,
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    # Test with env var set
    with patch.dict(os.environ, {"CHATBOT_ENDPOINT": "http://custom-endpoint:8080"}):
        contract = load_contract(path)
        assert contract.target_chatbot.endpoint == "http://custom-endpoint:8080"

    # Test with env var not set (should use default)
    with patch.dict(os.environ, {}, clear=False):
        if "CHATBOT_ENDPOINT" in os.environ:
            del os.environ["CHATBOT_ENDPOINT"]
        contract = load_contract(path)
        assert contract.target_chatbot.endpoint == "https://default.example.com"


def test_load_contract_resolves_env_vars_without_default(tmp_path):
    """Test that environment variables without defaults resolve to empty string when not set."""
    payload = _base_contract(tmp_path)
    payload["target_chatbot"] = {
        "enabled": True,
        "endpoint": "${CUSTOM_ENDPOINT}",
        "timeout_seconds": 30.0,
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))

    # Test with env var set
    with patch.dict(os.environ, {"CUSTOM_ENDPOINT": "http://my-endpoint"}):
        contract = load_contract(path)
        assert contract.target_chatbot.endpoint == "http://my-endpoint"

    # Test with env var not set (should be empty string)
    with patch.dict(os.environ, {}, clear=False):
        if "CUSTOM_ENDPOINT" in os.environ:
            del os.environ["CUSTOM_ENDPOINT"]
        contract = load_contract(path)
        assert contract.target_chatbot.endpoint == ""


def test_load_contract_parses_browser_chatbot_config(tmp_path):
    payload = _base_contract(tmp_path)
    payload["target_chatbot"] = {
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

    assert contract.target_chatbot.mode == "browser"
    assert contract.target_chatbot.browser is not None
    assert contract.target_chatbot.browser.browser_type == "edge"
    assert contract.target_chatbot.browser.url == "https://chat.example.com"
    assert contract.target_chatbot.browser.input_selector == "textarea"
    assert contract.target_chatbot.browser.submit_selector == "button[type='submit']"
    assert contract.target_chatbot.browser.response_selector == ".bot-message"
    assert contract.target_chatbot.browser.ready_selector == ".chat-ready"
    assert contract.target_chatbot.browser.response_timeout_seconds == 45.0
    assert contract.target_chatbot.browser.headless is True


def test_contract_to_dict_serializes_browser_chatbot_config(tmp_path):
    payload = _base_contract(tmp_path)
    payload["target_chatbot"] = {
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

    assert serialized["target_chatbot"]["browser"]["url"] == "https://chat.example.com"
