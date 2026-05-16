#!/usr/bin/env python3
"""Test script to verify environment variable resolution in contracts."""

import os
import tempfile
from pathlib import Path

# Set up test environment
os.environ["CHATBOT_ENDPOINT"] = "http://test-endpoint-from-env:9000"

from adaptive_synth_eval.config.contract import load_contract


def test_env_var_resolution():
    """Test that environment variables are resolved in contract files."""

    # Create a temporary contract file
    with tempfile.TemporaryDirectory() as tmp_dir:
        contract_path = Path(tmp_dir) / "test_contract.yaml"
        contract_path.write_text("""
simulation_suite:
  suite_id: test_suite
  target_application: test_bot
  run_mode: synthetic_chat_history_generation
  synthetic_flag: true

target_chatbot:
  enabled: true
  endpoint: "${CHATBOT_ENDPOINT:-https://default.example.com}"
  auth:
    type: bearer
    env_var: TEST_TOKEN
  timeout_seconds: 30.0

time_window:
  start_day: "2026-05-01"
  num_synthetic_days: 1
  compressed_runtime_minutes: 5

persona_pool:
  - persona_id: P001
    role: tester
    location: Test
    seniority: junior
    communication_style: direct
    hr_familiarity: low
    privacy_sensitivity: low

scenario_catalog:
  - scenario_id: S001
    domain: testing
    intent: verify_functionality
    expected_retrieval_topics: [testing]
    failure_injection:
      ambiguity: 0.1
    success_criteria:
      answers_grounded_in_policy: true

traffic_orchestration:
  total_conversations: 1
  conversation_turns:
    min: 3
    max: 3
  mix:
    - persona_id: P001
      scenario_id: S001
      weight: 1.0

output:
  base_dir: ./outputs
  run_id: test_run
""")

        # Load the contract
        contract = load_contract(contract_path)

        # Verify the endpoint was resolved from environment variable
        print(f"✓ Contract loaded successfully")
        print(f"✓ Endpoint from env var: {contract.target_chatbot.endpoint}")

        assert contract.target_chatbot.endpoint == "http://test-endpoint-from-env:9000", \
            f"Expected 'http://test-endpoint-from-env:9000', got '{contract.target_chatbot.endpoint}'"

        print("✓ Environment variable resolution works correctly!")

        # Test without the env var set
        del os.environ["CHATBOT_ENDPOINT"]

        contract2 = load_contract(contract_path)
        print(f"✓ Endpoint with default fallback: {contract2.target_chatbot.endpoint}")

        assert contract2.target_chatbot.endpoint == "https://default.example.com", \
            f"Expected 'https://default.example.com', got '{contract2.target_chatbot.endpoint}'"

        print("✓ Default fallback works correctly!")
        print("\n✅ All tests passed!")


if __name__ == "__main__":
    test_env_var_resolution()
