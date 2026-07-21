"""Integration tests for per-metric fingerprint-based versioning."""

import json
from pathlib import Path

from adaptive_synth_eval.cli import main
from adaptive_synth_eval.monitoring import runner as monitoring_runner
from adaptive_synth_eval.monitoring.fingerprint import (
    compute_evaluation_fingerprint,
    compute_metric_content_fingerprint,
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
        if value is True:
            base.append(flag)
            continue
        if value is False or value is None:
            continue
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
            assert "content_fingerprint" in vv["metrics"][key], (
                f"{key} missing content_fingerprint"
            )
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


def test_append_only_history_continues_from_saved_position(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_append"
    _write_chat_history(run_dir, total_rows=2)
    args = _monitor_args(run_dir, sample_size=1000)

    assert main(args) == 0
    history_path = run_dir / "chat_history.jsonl"
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "timestamp": "2026-01-01T00:02:00",
            "conversation_id": "conv-3",
            "turn_id": 3,
            "persona_id": "P001",
            "user_message": "How does policy apply to case 3?",
            "bot_response": "Policy answer for case 3.",
        }) + "\n")

    assert main(args) == 0

    assert len(_read_jsonl(run_dir / "monitoring_scores.jsonl")) == 3
    state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert state["chat_history_source"]["size_bytes"] == history_path.stat().st_size
    assert len(state["chat_history_source"]["sha256"]) == 64


def test_rewritten_history_rescans_and_refreshes_reference_input_batch(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_rewrite"
    _write_chat_history(run_dir, total_rows=1)
    history_path = run_dir / "chat_history.jsonl"
    row = _read_jsonl(history_path)[0]
    row["reference_context"] = "context-v1"
    history_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    args = _monitor_args(run_dir, sample_size=1000)

    assert main(args) == 0
    before = _read_jsonl(run_dir / "monitoring_scores.jsonl")[0]
    before_batches = before["value_versions"]["judge_batches"]

    row["reference_context"] = "context-v2"
    history_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert main(args) == 0

    after = _read_jsonl(run_dir / "monitoring_scores.jsonl")[0]
    after_batches = after["value_versions"]["judge_batches"]
    safety_id = next(
        key for key, value in after_batches.items()
        if value["evaluation_group"] == "safety"
    )
    performance_id = next(
        key for key, value in after_batches.items()
        if value["evaluation_group"] == "performance"
    )
    assert after_batches[safety_id]["input_fingerprint"] == before_batches[safety_id]["input_fingerprint"]
    assert after_batches[performance_id]["input_fingerprint"] != before_batches[performance_id]["input_fingerprint"]
    assert after["value_versions"]["metric_modes"]["groundedness"] == "reference_backed"


def test_retryable_fallback_rescans_and_refreshes_only_stale_batch(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_retry"
    _write_chat_history(run_dir, total_rows=1)
    args = _monitor_args(run_dir, sample_size=1000)
    assert main(args) == 0

    scores_path = run_dir / "monitoring_scores.jsonl"
    score = _read_jsonl(scores_path)[0]
    performance_id = next(
        key for key, value in score["value_versions"]["judge_batches"].items()
        if value["evaluation_group"] == "performance"
    )
    score["value_versions"]["judge_batches"][performance_id]["refresh_quality"] = (
        "heuristic_fallback"
    )
    scores_path.write_text(json.dumps(score) + "\n", encoding="utf-8")
    state_path = run_dir / "monitoring_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["retryable_fallbacks"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert main(args) == 0

    refreshed = _read_jsonl(scores_path)[0]
    assert all(
        batch["refresh_quality"] == "dry_run"
        for batch in refreshed["value_versions"]["judge_batches"].values()
    )
    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert final_state["retryable_fallbacks"] is False


def test_explicit_rescan_refreshes_only_stale_judge_batch(tmp_path, monkeypatch):
    run_dir = tmp_path / "outputs" / "runs" / "run_stale_batch_rescan"
    _write_chat_history(run_dir, total_rows=1)
    args = _monitor_args(run_dir, sample_size=1000)
    assert main(args) == 0

    scores_path = run_dir / "monitoring_scores.jsonl"
    score = _read_jsonl(scores_path)[0]
    safety_id = next(
        key for key, value in score["value_versions"]["judge_batches"].items()
        if value["evaluation_group"] == "safety"
    )
    performance_id = next(
        key for key, value in score["value_versions"]["judge_batches"].items()
        if value["evaluation_group"] == "performance"
    )
    safety_batch_before = dict(
        score["value_versions"]["judge_batches"][safety_id]
    )
    safety_metrics_before = json.loads(json.dumps(score["safety_metrics"]))
    score["value_versions"]["judge_batches"][performance_id][
        "refresh_quality"
    ] = "heuristic_fallback"
    score["performance_metrics"]["relevance"]["percent"] = -1.0
    scores_path.write_text(json.dumps(score) + "\n", encoding="utf-8")

    evaluated_batch_ids = []
    real_evaluate = monitoring_runner.MetricEvaluator.evaluate

    def record_evaluated_batches(self, *args, **kwargs):
        evaluated_batch_ids.append(kwargs.get("batch_ids"))
        return real_evaluate(self, *args, **kwargs)

    monkeypatch.setattr(
        monitoring_runner.MetricEvaluator,
        "evaluate",
        record_evaluated_batches,
    )
    assert main([*args, "--rescan"]) == 0

    assert evaluated_batch_ids == [{performance_id}]
    refreshed = _read_jsonl(scores_path)[0]
    assert refreshed["value_versions"]["judge_batches"][safety_id] == safety_batch_before
    assert refreshed["safety_metrics"] == safety_metrics_before
    assert refreshed["value_versions"]["judge_batches"][performance_id][
        "refresh_quality"
    ] == "dry_run"
    assert refreshed["performance_metrics"]["relevance"]["percent"] != -1.0
    state = json.loads(
        (run_dir / "monitoring_state.json").read_text(encoding="utf-8")
    )
    assert state["evaluated_rows"] == 1


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
    """Verify that composite and per-metric fingerprints are valid."""
    config = load_metrics_config()

    # Dry-run llm has no provider — fingerprint should use "dry_run".
    fp = compute_evaluation_fingerprint(
        metric_content_fingerprints=config.metric_content_fingerprints,
        model_provider="dry_run",
        model_identifier="dry_run",
    )
    assert len(fp) == 16

    # Every metric has a valid content fingerprint.
    for key, mdef in config.metrics.items():
        assert mdef.content_fingerprint is not None
        assert len(mdef.content_fingerprint) == 16

    # Every metric has a valid policy fingerprint.
    for key, mdef in config.metrics.items():
        pfp = compute_policy_fingerprint(
            metric_key=key,
            warn_below=mdef.warn_below,
            fail_below=mdef.fail_below,
        )
        assert len(pfp) == 16


def test_content_fingerprint_changes_with_prompt():
    """Changing a single metric's prompt changes its content fingerprint
    and therefore the composite evaluation fingerprint."""
    config = load_metrics_config()

    # Get the baseline composite fingerprint.
    baseline = compute_evaluation_fingerprint(
        metric_content_fingerprints=config.metric_content_fingerprints,
        model_provider="dry_run",
        model_identifier="dry_run",
    )

    # Simulate changing toxicity's prompt by computing a different content FP.
    tox = config.metrics["toxicity"]
    modified_tox_fp = compute_metric_content_fingerprint(
        metric_key="toxicity",
        prompt_template="A totally different evaluation prompt.",
        eval_input_key=tox.eval_input_key,
        invert_llm_score=tox.invert_llm_score,
        heuristic=tox.heuristic,
    )

    # The modified fingerprint must differ from the original.
    original_tox_fp = config.metric_content_fingerprints["toxicity"]
    assert modified_tox_fp != original_tox_fp, (
        "Changed prompt must produce different content fingerprint"
    )

    # The composite fingerprint must also change.
    modified_fps = dict(config.metric_content_fingerprints)
    modified_fps["toxicity"] = modified_tox_fp
    modified_composite = compute_evaluation_fingerprint(
        metric_content_fingerprints=modified_fps,
        model_provider="dry_run",
        model_identifier="dry_run",
    )
    assert modified_composite != baseline, (
        "Changing a metric's content fingerprint must change the composite fingerprint"
    )


def test_evaluation_fingerprint_changes_with_judge_protocol_or_metric_route():
    config = load_metrics_config()
    base_kwargs = {
        "metric_content_fingerprints": config.metric_content_fingerprints,
        "model_provider": "mixed",
        "model_identifier": "metric_routed",
        "judge_protocol_version": "protocol-v1",
        "judge_settings": {"temperature": 0.0, "max_tokens": 800},
        "metric_judge_fingerprints": {"toxicity": "judge-a"},
    }

    baseline = compute_evaluation_fingerprint(**base_kwargs)
    changed_protocol = compute_evaluation_fingerprint(
        **{**base_kwargs, "judge_protocol_version": "protocol-v2"}
    )
    changed_route = compute_evaluation_fingerprint(
        **{
            **base_kwargs,
            "metric_judge_fingerprints": {"toxicity": "judge-b"},
        }
    )

    assert changed_protocol != baseline
    assert changed_route != baseline
