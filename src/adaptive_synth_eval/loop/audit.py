from __future__ import annotations

from pathlib import Path
from typing import Any

from adaptive_synth_eval.loop.profiles import load_loop_profile
from adaptive_synth_eval.loop.state_store import get_loop_status


def build_loop_audit(
        *,
        profile_ref: str | None,
        output_dir: Path,
        profiles_dir: Path,
) -> dict[str, Any] | list[dict[str, Any]]:
    if profile_ref:
        return _audit_one(profile_ref=profile_ref, output_dir=output_dir, profiles_dir=profiles_dir)

    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(_profile_paths(profiles_dir)):
        stem = path.stem
        if stem in seen:
            continue
        seen.add(stem)
        reports.append(_audit_one(profile_ref=stem, output_dir=output_dir, profiles_dir=profiles_dir))
    return reports


def _audit_one(*, profile_ref: str, output_dir: Path, profiles_dir: Path) -> dict[str, Any]:
    profile = load_loop_profile(profile_ref, profiles_dir=profiles_dir)
    status = get_loop_status(profile_ref=profile.profile_id, output_dir=output_dir, profiles_dir=profiles_dir)
    initialized = isinstance(status, dict) and bool(status.get("initialized", True)) and bool(status.get("updated_at"))

    loops_dir = output_dir / "loops"
    files = {
        "STATE.md": (loops_dir / "STATE.md").exists(),
        "loop-budget.md": (loops_dir / "loop-budget.md").exists(),
        "loop-run-log.md": (loops_dir / "loop-run-log.md").exists(),
        "state_json": (loops_dir / "state" / f"{profile.profile_id}.json").exists(),
    }

    checker_policy = dict(profile.checker_policy or {})
    safeguards = {
        "denylist_enabled": bool(profile.denylist),
        "max_retry_attempts": int(checker_policy.get("max_retry_attempts", 2)),
        "allow_auto_resume": bool(checker_policy.get("allow_auto_resume", True)),
        "allow_auto_restart_stale_failed": bool(checker_policy.get("allow_auto_restart_stale_failed", True)),
        "safe_max_concurrency": checker_policy.get("safe_max_concurrency"),
        "paused": bool((status or {}).get("paused", profile.paused)) if isinstance(status, dict) else bool(
            profile.paused),
        "active_windows": list(profile.active_windows),
        "daily_run_cap": profile.daily_run_cap,
        "daily_token_cap": profile.daily_token_cap,
        "auto_pause_after_checker_failures": int(checker_policy.get("auto_pause_after_checker_failures", 3)),
    }

    checks = [
        bool(files["STATE.md"]),
        bool(files["loop-budget.md"]),
        bool(files["loop-run-log.md"]),
        bool(files["state_json"]),
    ]
    if profile.readiness_level in {"L2", "L3"}:
        checks.extend(
            [
                safeguards["max_retry_attempts"] >= 1,
                safeguards["allow_auto_resume"] or safeguards["allow_auto_restart_stale_failed"],
            ]
        )
    if profile.readiness_level == "L3":
        checks.extend(
            [
                safeguards["daily_run_cap"] is not None or safeguards["daily_token_cap"] is not None,
                bool(safeguards["active_windows"]),
                safeguards["auto_pause_after_checker_failures"] >= 1,
            ]
        )

    readiness_score = round((sum(1 for value in checks if value) / len(checks)) * 100, 1) if checks else 0.0

    return {
        "profile_id": profile.profile_id,
        "readiness_level": profile.readiness_level,
        "initialized": initialized,
        "status": status.get("status") if isinstance(status, dict) else "unknown",
        "files": files,
        "maker_checker_split": profile.readiness_level in {"L2", "L3"},
        "multi_profile_coordination_ready": profile.readiness_level == "L3",
        "l2_actions_supported": [
            "auto_resume_incomplete",
            "auto_restart_stale_failed",
            "apply_concurrency_cap",
            "regenerate_missing_summary",
        ] if profile.readiness_level in {"L2", "L3"} else [],
        "l3_controls_supported": [
            "kill_switch",
            "active_windows",
            "daily_run_cap",
            "daily_token_cap",
            "auto_pause_after_checker_failures",
            "priority_scheduler",
        ] if profile.readiness_level == "L3" else [],
        "safeguards": safeguards,
        "readiness_score": readiness_score,
    }


def _profile_paths(profiles_dir: Path) -> list[Path]:
    if not profiles_dir.exists():
        return []
    results: list[Path] = []
    for suffix in ("*.yaml", "*.yml", "*.json"):
        results.extend(sorted(profiles_dir.glob(suffix)))
    return results
