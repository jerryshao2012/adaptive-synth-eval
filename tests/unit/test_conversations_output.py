#!/usr/bin/env python3
"""Test script for output-conversations feature."""

import json
import tempfile
from pathlib import Path

from adaptive_synth_eval.config.contract import load_contract
from adaptive_synth_eval.engines.chat_history_simulation import run_simulation


def test_output_conversations():
    """Test that conversations.txt is generated with Persona/Bot labels."""

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create a minimal contract
        contract_data = {
            "simulation_suite": {
                "suite_id": "test_suite",
                "target_application": "test_bot",
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
                "random_seed": 42,
            },
            "output": {"base_dir": str(tmp_path / "outputs"), "run_id": "test_run"},
        }

        contract_path = tmp_path / "contract.json"
        contract_path.write_text(json.dumps(contract_data))

        # Load and run simulation with output_conversations=True
        contract = load_contract(contract_path)
        summary = run_simulation(contract, dry_run=True, output_conversations=True)

        # Check that conversations.txt was created
        conv_file = tmp_path / "outputs" / "runs" / "test_run" / "conversations.txt"

        print(f"✓ Summary: {summary['total_conversations']} conversations, {summary['total_turns']} turns")
        print(f"✓ Output directory: {summary['output_dir']}")

        if not conv_file.exists():
            print("✗ FAILED: conversations.txt was not created")
            return False

        print("✓ conversations.txt exists")

        # Read and verify content
        content = conv_file.read_text(encoding="utf-8")

        # Check for expected markers
        checks = [
            ("Persona (Turn 1):", "Persona label"),
            ("Bot (Turn 1):", "Bot label"),
            ("Conversation ID:", "Conversation header"),
            ("Persona: P001", "Persona info"),
            ("Scenario: S001", "Scenario info"),
            ("=", "Separator lines"),
        ]

        all_passed = True
        for marker, description in checks:
            if marker in content:
                print(f"✓ Found {description}: '{marker}'")
            else:
                print(f"✗ Missing {description}: '{marker}'")
                all_passed = False

        if all_passed:
            print("\n✅ All checks passed!")
            print("\n--- Sample of conversations.txt ---")
            # Print first 50 lines
            lines = content.split('\n')[:50]
            print('\n'.join(lines))
            print("...\n")
        else:
            print("\n❌ Some checks failed")

        return all_passed


if __name__ == "__main__":
    success = test_output_conversations()
    exit(0 if success else 1)
