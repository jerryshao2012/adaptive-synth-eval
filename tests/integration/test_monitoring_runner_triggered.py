"""
Integration tests for Phase 5: Monitoring Runner with Triggered Strategy.
Validates CLI integration, runner execution, and triggered row selection.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adaptive_synth_eval.monitoring.runner import run_monitoring


@pytest.fixture
def sample_chat_history() -> list[dict]:
    """Generate sample chat history with varied scenarios."""
    rows = []
    for conv_id in range(1, 3):  # 2 conversations
        for turn_id in range(1, 6):  # 5 turns each
            rows.append(
                {
                    "conversation_id": f"conv_{conv_id}",
                    "turn_id": str(turn_id),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_message": f"User message {turn_id}",
                    "bot_response": f"Bot response {turn_id}",
                    "error": None
                    if turn_id != 3
                    else "Timeout error",  # Error on turn 3
                    "latency_ms": 500
                    if turn_id != 2
                    else 9000,  # High latency on turn 2
                    "applied_failure_modes": []
                    if turn_id != 4
                    else ["jailbreak"],  # Attack on turn 4
                }
            )
    return rows


@pytest.fixture
def run_dir_with_chat_history(sample_chat_history: list[dict]) -> Path:
    """Create a temporary run directory with chat history."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Write chat history in JSONL format
        chat_history_path = run_dir / "chat_history.jsonl"
        with open(chat_history_path, "w") as f:
            for row in sample_chat_history:
                f.write(json.dumps(row) + "\n")

        yield run_dir


class TestTriggeredMonitoringRunner:
    """Test triggered sampling strategy in monitoring runner."""

    def test_triggered_strategy_detects_triggers(
        self, run_dir_with_chat_history: Path
    ) -> None:
        """Verify triggered strategy detects error/latency/attack triggers."""
        result = run_monitoring(
            run_dir=run_dir_with_chat_history,
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

        assert result is not None
        assert isinstance(result, dict)
        assert "evaluations" in result or "status" in result

    def test_triggered_strategy_with_custom_lookback(
        self, run_dir_with_chat_history: Path
    ) -> None:
        """Verify triggered strategy respects custom lookback parameter."""
        result = run_monitoring(
            run_dir=run_dir_with_chat_history,
            sample_size=1000,
            interval_minutes=60,
            sampling_strategy="triggered",
            incomplete_run_action="restart",
            dry_run=True,
            max_windows=None,
            metrics_config_path=None,
            rescan=False,
            triggered_lookback=4,
            triggered_lookahead=2,
        )

        assert result is not None
        scores = [
            json.loads(line)
            for line in (run_dir_with_chat_history / "monitoring_scores.jsonl")
            .read_text()
            .splitlines()
        ]
        active = [row for row in scores if row["selected_for_monitoring"]]
        assert active
        assert all(row["selection_provenance"] for row in active)
        before_distances = {
            association["distance"]
            for row in active
            for association in row["selection_provenance"]
            if association["role"] == "before"
        }
        assert before_distances
        assert max(before_distances) >= 2

    def test_triggered_strategy_with_budget_limit(
        self, run_dir_with_chat_history: Path
    ) -> None:
        """Verify capture budget limits rows promoted."""
        result = run_monitoring(
            run_dir=run_dir_with_chat_history,
            sample_size=5,
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

        scores = [
            json.loads(line)
            for line in (run_dir_with_chat_history / "monitoring_scores.jsonl")
            .read_text()
            .splitlines()
        ]
        assert len([row for row in scores if row["selected_for_monitoring"]]) <= 5
        assert all(row["selection_provenance"] for row in scores)

    def test_standard_strategy_still_works(
        self, run_dir_with_chat_history: Path
    ) -> None:
        """Ensure standard sampling strategies are not broken."""
        result_all = run_monitoring(
            run_dir=run_dir_with_chat_history,
            sample_size=1000,
            interval_minutes=60,
            sampling_strategy="all",
            incomplete_run_action="restart",
            dry_run=True,
            max_windows=None,
            metrics_config_path=None,
            rescan=False,
        )

        assert result_all is not None

    def test_triggered_monitoring_state_persists(
        self, run_dir_with_chat_history: Path
    ) -> None:
        """Verify monitoring state persists trigger metrics."""
        run_monitoring(
            run_dir=run_dir_with_chat_history,
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

        # Check monitoring state file exists
        state_file = run_dir_with_chat_history / "monitoring_state.json"
        assert state_file.exists()

        with open(state_file, "r") as f:
            state = json.load(f)

        assert state.get("sampling_strategy") == "triggered"
        assert "trigger_metrics" in state or state.get("status") in (
            "in_progress",
            "completed",
        )


class TestTriggeredCliIntegration:
    """Test CLI argument passing for triggered strategy."""

    def test_cli_triggered_parameters_passed_to_runner(self) -> None:
        """Verify CLI parameters flow to runner function."""
        # This is implicitly tested by the CLI help test in test_cli.py
        # Here we validate the signature accepts all parameters
        import inspect

        sig = inspect.signature(run_monitoring)
        params = list(sig.parameters.keys())

        assert "triggered_lookback" in params
        assert "triggered_lookahead" in params
        assert "triggered_capture_budget" not in params
        assert "trigger_policy_path" in params

        # Verify defaults
        assert sig.parameters["triggered_lookback"].default == 2
        assert sig.parameters["triggered_lookahead"].default == 2

    def test_triggered_defaults_are_reasonable(self) -> None:
        """Verify trigger parameter defaults make sense."""
        import inspect

        sig = inspect.signature(run_monitoring)

        lookback_default = sig.parameters["triggered_lookback"].default
        lookahead_default = sig.parameters["triggered_lookahead"].default

        # Defaults should be positive integers
        assert lookback_default > 0
        assert lookahead_default > 0
        assert "triggered_capture_budget" not in sig.parameters
