from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

RUN_STATE_FILE = "run_state.json"

_INCOMPLETE_ARTIFACT_HINTS = (
    "contract.normalized.json",
    "run_plan.json",
    "chat_history.jsonl",
    "conversations.jsonl",
    "turns.jsonl",
    "scores.jsonl",
    "generation_report.md",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_run_state(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / RUN_STATE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_run_state(run_dir: Path, payload: dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / RUN_STATE_FILE
    fd, tmp_name = tempfile.mkstemp(prefix=".run_state_", suffix=".tmp", dir=str(run_dir))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        # OneDrive-backed files can transiently lock on replace.
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt >= 4:
                    raise
                time.sleep(0.05)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return path


def detect_incomplete_run(run_dir: Path) -> dict[str, Any] | None:
    if not run_dir.exists():
        return None

    state = load_run_state(run_dir)
    if state is not None:
        status = str(state.get("status") or "").lower()
        if status != "completed":
            return {
                "reason": "run_state_not_completed",
                "status": status or "unknown",
                "completed_conversations": int(state.get("completed_conversations") or 0),
                "total_planned_conversations": int(state.get("total_planned_conversations") or 0),
                "state": state,
            }
        return None

    has_artifacts = any((run_dir / name).exists() for name in _INCOMPLETE_ARTIFACT_HINTS)
    has_summary = (run_dir / "run_summary.json").exists()
    if has_artifacts and not has_summary:
        return {
            "reason": "legacy_artifacts_without_summary",
            "status": "unknown",
            "completed_conversations": 0,
            "total_planned_conversations": 0,
            "state": None,
        }
    return None


def clear_run_directory(run_dir: Path) -> None:
    if not run_dir.exists():
        return

    def _handle_remove_error(func: Any, path: str, exc_info: tuple[type[BaseException], BaseException, Any]) -> None:
        error = exc_info[1]
        if isinstance(error, FileNotFoundError):
            return
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except FileNotFoundError:
            return

    # OneDrive sync and antivirus scanners can hold transient file locks.
    for attempt in range(6):
        try:
            shutil.rmtree(run_dir, onerror=_handle_remove_error)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt >= 5:
                raise
            time.sleep(0.1 * (attempt + 1))
