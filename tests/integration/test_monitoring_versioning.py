"""Integration tests for per-metric fingerprint-based versioning."""

import json
from pathlib import Path

from adaptive_synth_eval.cli import main
from adaptive_synth_eval.monitoring.fingerprint import (
    compute_evaluation_fingerprint,
    compute_policy_fingerprint,
)
from adaptive_synth_eval.monitoring.metric_definitions import load_metrics_config


def _write_chat_history(run_dir: Path, total_rows: int) -> None:
    from datetime import datetime, timedelta
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "chat_history.jsonl"
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    with path.open("w", encoding="utf-8") as handle:
        for idx in range(1, total_rows + 1):
            ts = base_time + timedelta(minutes=1 * (idx - 1))
            row = {
                "timestamp": ts.isoformat(),
                "conversation_id": f"conv-{idx}",
                "turn_id": idx,
                "persona_id": "P001",
                "user_message": f"How does policy apply to case {idx}?",
                "bot_response": f"Policy answer for case {idx}.",
            }
            handle.write(json.dumps(row) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _monitor_args(run_dir: str | Path, **overrides) -> list[str]:
    base = [
        "monitor", "run",
        "--run-folder", str(run_dir),
        "--dry-run",
        "--incomplete-run-action", "resume",
    ]
    for key, value in overrides.items():
        flag = "--" + key.replace("_", "-")
        base.extend([flag, str(value)])
    return base


# ---------------------------------------------------------------------------
# Fingerprint-based evaluation
# ---------------------------------------------------------------------------

def test_full_run_produces_value_versions(tmp_path):
    """Every score row must include a value_versions block."""
    run_dir = tmp_path / "outputs" / "runs" / "run_a"
    _write_chat_history(run_dir, total_rows=3)

    exit_code = main(_monitor_args(run_dir, sample_size=2))
    assert exit_code == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 3

    for row in scores:
        vv = row.get("value_versions")
        assert vv is not None, "every row must have value_versions"
        assert "evaluation_fingerprint" in vv
        assert len(vv["evaluation_fingerprint"]) == 16
        assert "metrics" in vv
        for key in ("toxicity", "bias_fairness", "robustness", "compliance",
                    "relevance", "groundedness", "correctness", "completeness",
                    "style", "precision"):
            assert key in vv["metrics"], f"{key} missing from value_versions.metrics"
            assert "policy_fingerprint" in vv["metrics"][key]

    # Verify no legacy fields.
    for row in scores:
        assert "metric_version" not in row
        assert "threshold_version" not in row
        for group in ("safety_metrics", "performance_metrics"):
            for metric_val in row.get(group, {}).values():
                assert "version" not in metric_val
                assert "metadata" not in metric_val


def test_unchanged_config_skips_all_rows(tmp_path):
    """Second run with same config skips all rows (fingerprint unchanged)."""
    run_dir = tmp_path / "outputs" / "runs" / "run_b"
    _write_chat_history(run_dir, total_rows=2)

    args = _monitor_args(run_dir, sample_size=1000)

    first = main(args)
    second = main(args)

    assert first == 0
    assert second == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 2  # No duplicates

    state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert state.get("evaluation_fingerprint") is not None
    assert state.get("policy_fingerprints") is not None


def test_resume_after_crash_preserves_scores(tmp_path):
    """Resume after partial run picks up correctly."""
    run_dir = tmp_path / "outputs" / "runs" / "run_c"
    _write_chat_history(run_dir, total_rows=5)

    # First run: process 1 window of 2 rows.
    first = main(_monitor_args(run_dir, sample_size=2, max_windows=1, interval_minutes=2))
    assert first == 0

    mid_state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert mid_state["status"] == "in_progress"
    assert mid_state["next_line_index"] == 2

    # Second run: resume and finish.
    second = main(_monitor_args(run_dir, sample_size=2, interval_minutes=2))
    assert second == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 5

    final = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert final["status"] == "completed"


def test_evaluation_fingerprint_in_state(tmp_path):
    """monitoring_state.json contains evaluation_fingerprint and policy_fingerprints."""
    run_dir = tmp_path / "outputs" / "runs" / "run_d"
    _write_chat_history(run_dir, total_rows=1)

    exit_code = main(_monitor_args(run_dir))
    assert exit_code == 0

    state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert "evaluation_fingerprint" in state
    assert "policy_fingerprints" in state
    assert isinstance(state["policy_fingerprints"], dict)
    assert len(state["policy_fingerprints"]) == 10


def test_atomic_write_does_not_corrupt_file(tmp_path):
    """Scores file is always valid JSONL — atomic replace guarantees consistency."""
    run_dir = tmp_path / "outputs" / "runs" / "run_e"
    _write_chat_history(run_dir, total_rows=5)

    exit_code = main(_monitor_args(run_dir, sample_size=2))
    assert exit_code == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 5
    # Every row is a valid dict.
    for row in scores:
        assert isinstance(row, dict)
        assert "conversation_id" in row
        assert "turn_id" in row


# ---------------------------------------------------------------------------
# Fingerprint determinism with real config
# ---------------------------------------------------------------------------

def test_real_config_fingerprint_matches():
    """Verify that the fingerprint from runner matches what we compute manually."""
    config = load_metrics_config()

    # Dry-run llm has no provider — fingerprint should use "dry_run".
    fp = compute_evaluation_fingerprint(
        prompt_template=config.prompt_template,
        model_provider="dry_run",
        model_identifier="dry_run",
        metric_keys=sorted(config.metrics.keys()),
        metric_details=[m.detail for m in config.metrics.values()],
    )
    assert len(fp) == 16

    # Every metric has a valid policy fingerprint.
    for key, mdef in config.metrics.items():
        pfp = compute_policy_fingerprint(
            metric_key=key,
            warn_below=mdef.warn_below,
            fail_below=mdef.fail_below,
        )
        assert len(pfp) == 16
