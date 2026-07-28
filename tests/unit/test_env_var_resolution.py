"""Tests for environment variable resolution in synth contracts."""

import json

from adaptive_synth_eval.config.contract import load_contract


def test_env_var_resolution_uses_env_value_then_default(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    contract_path = tmp_path / "test_contract.yaml"
    payload = build_synth_contract_payload(base_dir="./outputs", run_id="test_run")
    payload["target"] = {
        "enabled": True,
        "endpoint": "${CHATBOT_ENDPOINT:-https://default.example.com}",
        "auth": {"type": "bearer", "env_var": "TEST_TOKEN"},
        "timeout_seconds": 30.0,
    }
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("CHATBOT_ENDPOINT", "http://test-endpoint-from-env:9000")
    contract = load_contract(contract_path)
    assert contract.target.endpoint == "http://test-endpoint-from-env:9000"

    monkeypatch.delenv("CHATBOT_ENDPOINT", raising=False)
    contract_default = load_contract(contract_path)
    assert contract_default.target.endpoint == "https://default.example.com"
