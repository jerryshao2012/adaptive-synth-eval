"""
Quick verification test to confirm trigger metrics are persisted to monitoring state.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from adaptive_synth_eval.monitoring.runner import run_monitoring


def test_trigger_metrics_persisted_to_state():
    """Verify trigger metrics are written to monitoring_state.json."""
    # Create sample chat history
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)

        chat_history_path = run_dir / "chat_history.jsonl"
        with open(chat_history_path, "w") as f:
            # Write 10 rows: include errors/high latency to trigger detection
            for i in range(1, 11):
                row = {
                    "conversation_id": f"conv_1",
                    "turn_id": str(i),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_message": f"Message {i}",
                    "bot_response": f"Response {i}",
                    "error": "Timeout" if i == 3 else None,
                    "latency_ms": 9000 if i == 5 else 500,
                    "applied_failure_modes": ["jailbreak"] if i == 7 else [],
                }
                f.write(json.dumps(row) + "\n")

        # Run with triggered strategy
        run_monitoring(
            run_dir=run_dir,
            sample_size=1000,
            interval_minutes=60,
            sampling_strategy="triggered",
            incomplete_run_action="restart",
            dry_run=True,
            max_windows=None,
            metrics_config_path=None,
            rescan=False,
            triggered_lookback=2,
            triggered_lookahead=2,
        )

        # Verify monitoring state file exists and contains trigger metrics
        state_file = run_dir / "monitoring_state.json"
        assert state_file.exists(), "monitoring_state.json not created"

        with open(state_file, "r") as f:
            state = json.load(f)

        # Check exact counts for the deterministic fixture.
        assert "trigger_metrics" in state, "trigger_metrics not in state"
        metrics = state["trigger_metrics"]

        assert "triggers_detected" in metrics, "triggers_detected not in metrics"
        assert "rows_promoted" in metrics, "rows_promoted not in metrics"
        assert "budget_used" in metrics, "budget_used not in metrics"

        assert metrics["triggers_detected"] == 4
        assert metrics["rows_promoted"] == 9
        assert metrics["budget_used"] == 9
        assert metrics["budget_drops"] == 0
        assert metrics["pending_lookahead"] == 0


if __name__ == "__main__":
    test_trigger_metrics_persisted_to_state()
    print("\n✅ Trigger metrics persistence verified!")
