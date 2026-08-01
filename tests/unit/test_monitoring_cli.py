import json
from pathlib import Path

from adaptive_synth_eval.cli import main


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
    """Build CLI args with dry-run and resume as defaults."""
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


def test_metrics_serve_launches_uvicorn_app_factory(monkeypatch):
    calls = []

    def fake_run(app, **kwargs):
        calls.append((app, kwargs))

    monkeypatch.setattr("uvicorn.run", fake_run)

    exit_code = main([
        "metrics",
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
        "--workers",
        "3",
    ])

    assert exit_code == 0
    assert calls == [(
        "adaptive_synth_eval.metrics_api.app:create_app",
        {
            "factory": True,
            "host": "0.0.0.0",
            "port": 9000,
            "workers": 3,
        },
    )]


def test_monitoring_cli_dry_run_writes_scores_and_state(tmp_path, capsys):
    run_dir = tmp_path / "outputs" / "runs" / "run_a"
    _write_chat_history(run_dir, total_rows=3)

    exit_code = main(_monitor_args(run_dir, sample_size=2, max_windows=3))

    assert exit_code == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 3
    # All rows must have value_versions instead of metric_version.
    for row in scores:
        assert "value_versions" in row
        assert "evaluation_fingerprint" in row["value_versions"]

    state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    assert state["next_line_index"] == 3
    assert state["max_windows"] == 3
    assert "evaluation_fingerprint" in state

    progress_text = (run_dir / "eval_progress.md").read_text(encoding="utf-8")
    assert "# Eval Progress" in progress_text
    assert "- Status: completed" in progress_text
    assert "Evaluation Fingerprint" in progress_text
    assert "- Max Windows: 3" in progress_text

    summary = json.loads(capsys.readouterr().out)
    assert summary["max_windows"] == 3
    assert summary["rescan"] is False


def test_monitoring_cli_skips_duplicate_same_fingerprint(tmp_path):
    """Second run with same config skips all rows (same evaluation fingerprint)."""
    run_dir = tmp_path / "outputs" / "runs" / "run_b"
    _write_chat_history(run_dir, total_rows=2)

    args = _monitor_args(run_dir, sample_size=1000)

    first_exit = main(args)
    second_exit = main(args)

    assert first_exit == 0
    assert second_exit == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    # Only 2 unique rows, no duplicates despite two runs.
    assert len(scores) == 2


def test_monitoring_cli_resume_after_partial_windows(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_c"
    _write_chat_history(run_dir, total_rows=5)

    first_exit = main(_monitor_args(run_dir, sample_size=2, max_windows=1, interval_minutes=2))
    assert first_exit == 0

    mid_state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert mid_state["status"] == "in_progress"
    assert mid_state["next_line_index"] == 2
    assert mid_state["max_windows"] == 1
    assert "evaluation_fingerprint" in mid_state
    progress_text = (run_dir / "eval_progress.md").read_text(encoding="utf-8")
    assert "- Max Windows: 1" in progress_text

    second_exit = main(_monitor_args(run_dir, sample_size=2, interval_minutes=2))
    assert second_exit == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 5

    final_state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert final_state["status"] == "completed"
    assert final_state["next_line_index"] == 5
    assert "evaluation_fingerprint" in final_state


def test_monitoring_cli_random_sampling(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_random"
    _write_chat_history(run_dir, total_rows=10)

    # Use sample_size 3 with random strategy. Since fallback timestamps are 1 second apart,
    # and interval-minutes defaults to 60, all 10 rows fit in the first window.
    exit_code = main(_monitor_args(run_dir, sample_size=3, sampling_strategy="random"))
    assert exit_code == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 3

    state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    assert state["evaluated_rows"] == 3
    assert state["skipped_rows"] == 7


def test_monitoring_cli_systematic_sampling(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_systematic"
    _write_chat_history(run_dir, total_rows=10)

    # Use sample_size 2 with systematic strategy.
    exit_code = main(_monitor_args(run_dir, sample_size=2, sampling_strategy="systematic"))
    assert exit_code == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 2

    # With 10 rows, k = 10 / 2 = 5.
    # Index 0 (conv-1) and Index 5 (conv-6) should be selected.
    conv_ids = {row["conversation_id"] for row in scores}
    assert conv_ids == {"conv-1", "conv-6"}


def test_monitoring_cli_completed_unchanged_rescan_reuses_scores(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_systematic_rescan"
    _write_chat_history(run_dir, total_rows=10)
    first_args = _monitor_args(
        run_dir, sample_size=2, sampling_strategy="systematic"
    )

    assert main(first_args) == 0
    scores_path = run_dir / "monitoring_scores.jsonl"
    scores_before = scores_path.read_bytes()
    rows_before = _read_jsonl(scores_path)

    assert main([*first_args, "--rescan"]) == 0

    assert scores_path.read_bytes() == scores_before
    assert _read_jsonl(scores_path) == rows_before
    state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    assert state["next_line_index"] == 10
    assert state["evaluated_rows"] == 0


def test_monitoring_scores_copy_profile_provenance_without_changing_timestamp(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_profiled"
    _write_chat_history(run_dir, total_rows=1)
    history_path = run_dir / "chat_history.jsonl"
    chat_row = _read_jsonl(history_path)[0]
    chat_row.update(
        {
            "timestamp": "2026-05-02T08:15:30.123456",
            "recipe_id": "recipe-support",
            "profile_period_id": "morning",
            "profile_period_instance_id": "2026-05-02/morning",
            "profile_period_start": "2026-05-02T08:00:00",
            "profile_period_end": "2026-05-02T10:00:00",
            "conversation_mode": "support",
            "behavior_mode": "polite",
            "synthetic_slot": 3,
            "synthetic_day": "2026-05-02",
            "scenario_id": "scenario-1",
            "adversarial_scenario_id": "attack-1",
        }
    )
    history_path.write_text(json.dumps(chat_row) + "\n", encoding="utf-8")

    assert main(_monitor_args(run_dir, sample_size=1)) == 0

    score = _read_jsonl(run_dir / "monitoring_scores.jsonl")[0]
    for field in (
        "recipe_id",
        "profile_period_id",
        "profile_period_instance_id",
        "profile_period_start",
        "profile_period_end",
        "conversation_mode",
        "behavior_mode",
        "synthetic_slot",
        "synthetic_day",
        "scenario_id",
        "adversarial_scenario_id",
        "persona_id",
    ):
        assert score[field] == chat_row[field]
    assert score["timestamp"] == chat_row["timestamp"]
    assert score["sample_window_id"] == 1


def test_monitoring_resume_retains_profile_provenance(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_profiled_resume"
    _write_chat_history(run_dir, total_rows=2)
    history_path = run_dir / "chat_history.jsonl"
    chat_rows = _read_jsonl(history_path)
    for index, chat_row in enumerate(chat_rows, 1):
        chat_row.update(
            {
                "profile_period_id": "morning" if index == 1 else "afternoon",
                "profile_period_instance_id": (
                    "2026-01-01/morning" if index == 1 else "2026-01-01/afternoon"
                ),
                "profile_period_start": f"2026-01-01T0{7 + index}:00:00",
                "profile_period_end": f"2026-01-01T{9 + index:02d}:00:00",
                "conversation_mode": "support",
                "behavior_mode": "polite",
                "synthetic_slot": index,
                "synthetic_day": "2026-01-01",
                "recipe_id": f"recipe-{index}",
            }
        )
    history_path.write_text(
        "".join(json.dumps(row) + "\n" for row in chat_rows), encoding="utf-8"
    )

    first_args = _monitor_args(
        run_dir, sample_size=1, max_windows=1, interval_minutes=1
    )
    assert main(first_args) == 0
    assert main(_monitor_args(run_dir, sample_size=1, interval_minutes=1)) == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert [row["profile_period_instance_id"] for row in scores] == [
        "2026-01-01/morning",
        "2026-01-01/afternoon",
    ]
    assert [row["sample_window_id"] for row in scores] == [1, 2]


def test_monitoring_rescan_refreshes_reused_row_provenance_only(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_profiled_rescan"
    _write_chat_history(run_dir, total_rows=1)
    history_path = run_dir / "chat_history.jsonl"
    chat_row = _read_jsonl(history_path)[0]
    chat_row.update(
        {
            "timestamp": "2026-01-01T00:00:00.111222",
            "profile_period_id": "morning",
            "profile_period_instance_id": "2026-01-01/morning",
            "profile_period_start": "2026-01-01T08:00:00",
            "profile_period_end": "2026-01-01T10:00:00",
        }
    )
    history_path.write_text(json.dumps(chat_row) + "\n", encoding="utf-8")
    args = _monitor_args(run_dir, sample_size=1)
    assert main(args) == 0

    before = _read_jsonl(run_dir / "monitoring_scores.jsonl")[0]
    chat_row["timestamp"] = "2026-01-01T00:00:00.987654"
    chat_row["profile_period_id"] = "peak"
    chat_row["profile_period_instance_id"] = "2026-01-01/peak"
    chat_row["profile_period_start"] = "2026-01-01T09:00:00"
    chat_row.pop("profile_period_end")
    history_path.write_text(json.dumps(chat_row) + "\n", encoding="utf-8")

    assert main([*args, "--rescan"]) == 0

    after = _read_jsonl(run_dir / "monitoring_scores.jsonl")[0]
    assert after["profile_period_id"] == "peak"
    assert after["profile_period_instance_id"] == "2026-01-01/peak"
    assert after["profile_period_start"] == "2026-01-01T09:00:00"
    assert "profile_period_end" not in after
    assert after["timestamp"] == chat_row["timestamp"]
    assert after["timestamp"] != before["timestamp"]
    assert after["sample_window_id"] == before["sample_window_id"]
    assert after["safety_metrics"] == before["safety_metrics"]
    assert after["performance_metrics"] == before["performance_metrics"]


def test_legacy_monitoring_scores_omit_profile_fields(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_legacy"
    _write_chat_history(run_dir, total_rows=1)

    assert main(_monitor_args(run_dir, sample_size=1)) == 0

    score = _read_jsonl(run_dir / "monitoring_scores.jsonl")[0]
    for field in (
        "recipe_id",
        "profile_period_id",
        "profile_period_instance_id",
        "profile_period_start",
        "profile_period_end",
        "conversation_mode",
        "behavior_mode",
        "synthetic_slot",
        "synthetic_day",
        "scenario_id",
        "adversarial_scenario_id",
    ):
        assert field not in score


def test_monitoring_cli_rescan_with_broader_systematic_sample_adds_rows(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_broader_rescan"
    _write_chat_history(run_dir, total_rows=10)

    assert main(_monitor_args(
        run_dir, sample_size=2, sampling_strategy="systematic"
    )) == 0
    assert len(_read_jsonl(run_dir / "monitoring_scores.jsonl")) == 2

    assert main(_monitor_args(
        run_dir,
        sample_size=4,
        sampling_strategy="systematic",
        rescan=True,
    )) == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 4
    state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert state["evaluated_rows"] == 2
