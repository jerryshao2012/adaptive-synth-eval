import json

from pathlib import Path

from adaptive_synth_eval.cli import main


def _write_chat_history(run_dir: Path, total_rows: int) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "chat_history.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for idx in range(1, total_rows + 1):
            row = {
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


def test_monitoring_cli_dry_run_writes_scores_and_state(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_a"
    _write_chat_history(run_dir, total_rows=3)

    exit_code = main(
        [
            "monitor",
            "run",
            "--run-folder",
            str(run_dir),
            "--sample-size",
            "2",
            "--metric-version",
            "v1",
            "--dry-run",
            "--incomplete-run-action",
            "resume",
        ]
    )

    assert exit_code == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 3
    assert all(row["metric_version"] == "v1" for row in scores)

    state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    assert state["next_line_index"] == 3

    progress_text = (run_dir / "eval_progress.md").read_text(encoding="utf-8")
    assert "# Eval Progress" in progress_text
    assert "- Status: completed" in progress_text


def test_monitoring_cli_skips_duplicate_same_metric_version(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_b"
    _write_chat_history(run_dir, total_rows=2)

    first_exit = main(
        [
            "monitor",
            "run",
            "--run-folder",
            str(run_dir),
            "--sample-size",
            "1000",
            "--metric-version",
            "v1",
            "--dry-run",
            "--incomplete-run-action",
            "resume",
        ]
    )
    second_exit = main(
        [
            "monitor",
            "run",
            "--run-folder",
            str(run_dir),
            "--sample-size",
            "1000",
            "--metric-version",
            "v1",
            "--dry-run",
            "--incomplete-run-action",
            "resume",
        ]
    )

    assert first_exit == 0
    assert second_exit == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 2


def test_monitoring_cli_resume_after_partial_windows(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "run_c"
    _write_chat_history(run_dir, total_rows=5)

    first_exit = main(
        [
            "monitor",
            "run",
            "--run-folder",
            str(run_dir),
            "--sample-size",
            "2",
            "--max-windows",
            "1",
            "--metric-version",
            "v1",
            "--dry-run",
            "--incomplete-run-action",
            "resume",
        ]
    )
    assert first_exit == 0

    mid_state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert mid_state["status"] == "in_progress"
    assert mid_state["next_line_index"] == 2

    second_exit = main(
        [
            "monitor",
            "run",
            "--run-folder",
            str(run_dir),
            "--sample-size",
            "2",
            "--metric-version",
            "v1",
            "--dry-run",
            "--incomplete-run-action",
            "resume",
        ]
    )

    assert second_exit == 0

    scores = _read_jsonl(run_dir / "monitoring_scores.jsonl")
    assert len(scores) == 5

    final_state = json.loads((run_dir / "monitoring_state.json").read_text(encoding="utf-8"))
    assert final_state["status"] == "completed"
    assert final_state["next_line_index"] == 5
