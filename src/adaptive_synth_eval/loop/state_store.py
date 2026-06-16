from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from adaptive_synth_eval.artifacts.run_state import now_iso
from adaptive_synth_eval.loop.profiles import LoopProfile, LoopProfileError, load_loop_profile


def initialize_loop_assets(profile: LoopProfile, *, output_dir: Path = Path("outputs")) -> dict[str, Any]:
    loops_dir = _loop_root(output_dir)
    state_dir = loops_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    state_path = _loop_state_path(profile.profile_id, output_dir)
    existing = _read_json(state_path)
    timestamp = now_iso()
    state = _build_initial_state(profile, existing=existing, timestamp=timestamp)
    _write_json_atomic(state_path, state)

    states = _load_all_states(output_dir)
    _write_text_atomic(loops_dir / "STATE.md", _render_state_markdown(states, generated_at=timestamp))
    _write_text_atomic(loops_dir / "loop-budget.md", _render_budget_markdown(states, generated_at=timestamp))
    _append_run_log(loops_dir / "loop-run-log.md", profile.profile_id, "initialized", profile.source_path, timestamp)

    return {
        "profile_id": profile.profile_id,
        "status": state["status"],
        "state_path": str(state_path),
        "state_markdown_path": str(loops_dir / "STATE.md"),
        "budget_markdown_path": str(loops_dir / "loop-budget.md"),
        "run_log_path": str(loops_dir / "loop-run-log.md"),
        "created": existing is None,
    }


def record_loop_cycle(
        profile: LoopProfile,
        *,
        output_dir: Path = Path("outputs"),
        run_results: list[dict[str, Any]],
        planner_decision: dict[str, Any] | None = None,
        reflection_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_loop_assets(profile, output_dir=output_dir)
    state_path = _loop_state_path(profile.profile_id, output_dir)
    state = _read_json(state_path)
    if state is None:
        raise LoopProfileError(f"Loop state not found for profile: {profile.profile_id}")

    timestamp = now_iso()
    total_runs = len(run_results)
    total_errors = sum(int(item.get("errors") or 0) for item in run_results)
    failed_runs = sum(1 for item in run_results if str(item.get("status") or "") != "completed")
    outcome_status = "completed"
    if failed_runs:
        outcome_status = "completed_with_errors"

    planner_decision = dict(planner_decision or {})
    reflection_decision = dict(reflection_decision or {})
    human_inbox = list(state.get("human_inbox") or [])
    for item in reflection_decision.get("escalation_items") or []:
        text = str(item).strip()
        if text:
            human_inbox.append(text)

    last_cycle = {
        "timestamp": timestamp,
        "ai_reasoning": planner_decision.get("ai_reasoning") or "Planner reasoning unavailable.",
        "ai_hypothesis": planner_decision.get("ai_hypothesis"),
        "recommended_action": planner_decision.get("recommended_action") or (
            f"Review the latest {total_runs} run summaries and loop run log for follow-up decisions."
        ),
        "checker_decision": "AUTO_APPROVED_REPORT_ONLY",
        "planner_source": planner_decision.get("source"),
        "reflection_source": reflection_decision.get("source"),
        "outcome": {
            "run_status": outcome_status,
            "key_finding": reflection_decision.get("key_finding") or (
                f"Executed {total_runs} target run(s) with {total_errors} reported error(s)."
            ),
            "ai_reflection": reflection_decision.get("ai_reflection") or (
                "AI reflection unavailable; review run_summary.json outputs and loop-run-log.md."
            ),
            "follow_up_enabled": bool(reflection_decision.get("follow_up_enabled", False)),
            "escalation_items": [str(item) for item in (reflection_decision.get("escalation_items") or [])],
        },
    }

    recent_runs = list(state.get("recent_runs") or [])
    recent_runs.extend(run_results)
    state["last_cycle"] = last_cycle
    state["recent_runs"] = recent_runs[-20:]
    state["status"] = outcome_status
    state["human_decision_required"] = bool(
        total_errors or failed_runs or reflection_decision.get("follow_up_enabled") or human_inbox
    )
    state["human_inbox"] = human_inbox[-20:]
    state["updated_at"] = timestamp
    budget = dict(state.get("budget") or _initial_budget_state(timestamp))
    budget["last_updated"] = timestamp
    state["budget"] = budget
    _write_json_atomic(state_path, state)

    states = _load_all_states(output_dir)
    loops_dir = _loop_root(output_dir)
    _write_text_atomic(loops_dir / "STATE.md", _render_state_markdown(states, generated_at=timestamp))
    _write_text_atomic(loops_dir / "loop-budget.md", _render_budget_markdown(states, generated_at=timestamp))
    for item in run_results:
        _append_run_log(
            loops_dir / "loop-run-log.md",
            profile.profile_id,
            f"run {item.get('status', 'completed')} run_id={item.get('run_id', 'unknown')} contract={item.get('contract', 'unknown')}",
            profile.source_path,
            timestamp,
        )
    _append_run_log(
        loops_dir / "loop-run-log.md",
        profile.profile_id,
        f"cycle {outcome_status} total_runs={total_runs} total_errors={total_errors}",
        profile.source_path,
        timestamp,
    )
    return state


def get_loop_status(
        *,
        profile_ref: str | None = None,
        output_dir: Path = Path("outputs"),
        profiles_dir: Path = Path("loops/profiles"),
) -> Any:
    if profile_ref:
        state = _read_json(_loop_state_path(profile_ref, output_dir))
        if state is not None:
            return state
        profile = load_loop_profile(profile_ref, profiles_dir=profiles_dir)
        return {
            "profile_id": profile.profile_id,
            "initialized": False,
            "status": "not_initialized",
            "source_path": str(profile.source_path),
            "readiness_level": profile.readiness_level,
            "cadence": profile.cadence,
            "targets": [target.__dict__ for target in profile.targets],
        }

    return _load_all_states(output_dir)


def _build_initial_state(profile: LoopProfile, *, existing: dict[str, Any] | None, timestamp: str) -> dict[str, Any]:
    if existing is not None:
        state = dict(existing)
        state["updated_at"] = timestamp
        state.setdefault("version", 1)
        state.setdefault("profile_id", profile.profile_id)
        state.setdefault("loop_id", profile.profile_id)
        state.setdefault("last_cycle", None)
        state.setdefault("recent_runs", [])
        state.setdefault("budget", _initial_budget_state(timestamp))
        return state

    return {
        "version": 1,
        "loop_id": profile.profile_id,
        "profile_id": profile.profile_id,
        "status": "initialized",
        "readiness_level": profile.readiness_level,
        "cadence": profile.cadence,
        "profile_path": str(profile.source_path),
        "created_at": timestamp,
        "updated_at": timestamp,
        "max_iterations_per_cycle": profile.max_iterations_per_cycle,
        "budget_policy_ref": profile.budget_policy_ref,
        "targets": [target.__dict__ for target in profile.targets],
        "escalation_rules": list(profile.escalation_rules),
        "human_gates": list(profile.human_gates),
        "denylist": list(profile.denylist),
        "checker_policy": dict(profile.checker_policy),
        "llm_config": None if profile.llm_config is None else profile.llm_config.__dict__,
        "human_decision_required": False,
        "human_inbox": [],
        "last_cycle": None,
        "recent_runs": [],
        "budget": _initial_budget_state(timestamp),
    }


def _initial_budget_state(timestamp: str) -> dict[str, Any]:
    return {
        "daily_cap_tokens": None,
        "weekly_cap_tokens": None,
        "spent_today_tokens": 0,
        "spent_this_week_tokens": 0,
        "last_updated": timestamp,
    }


def _load_all_states(output_dir: Path) -> list[dict[str, Any]]:
    state_dir = _loop_root(output_dir) / "state"
    if not state_dir.exists():
        return []
    states: list[dict[str, Any]] = []
    for path in sorted(state_dir.glob("*.json")):
        payload = _read_json(path)
        if payload is not None:
            states.append(payload)
    return states


def _render_state_markdown(states: list[dict[str, Any]], *, generated_at: str) -> str:
    lines = ["# Loop State", "", f"Generated: {generated_at}"]
    if not states:
        lines.extend(["", "No loop profiles initialized."])
        return "\n".join(lines) + "\n"

    for state in states:
        lines.extend([
            "",
            f"## {state.get('profile_id', 'unknown')}",
            f"- Status: {state.get('status', 'unknown')}",
            f"- Readiness level: {state.get('readiness_level', 'unknown')}",
            f"- Cadence: {state.get('cadence', 'unknown')}",
            f"- Last updated: {state.get('updated_at', 'unknown')}",
            f"- Human decision required: {'yes' if state.get('human_decision_required') else 'no'}",
        ])
        targets = state.get("targets") or []
        if targets:
            lines.append("- Targets:")
            for target in targets:
                descriptor = str(target.get("contract", "unknown"))
                persona = target.get("persona")
                scenario = target.get("scenario")
                if persona:
                    descriptor = f"{descriptor} [persona={persona}]"
                if scenario:
                    descriptor = f"{descriptor} [scenario={scenario}]"
                lines.append(f"  - {descriptor}")
        last_cycle = state.get("last_cycle")
        if isinstance(last_cycle, dict):
            lines.append(f"- Last cycle timestamp: {last_cycle.get('timestamp', 'unknown')}")
            if last_cycle.get("ai_hypothesis"):
                lines.append(f"- Last AI hypothesis: {last_cycle['ai_hypothesis']}")
            if last_cycle.get("ai_reasoning"):
                lines.append(f"- Planner reasoning: {last_cycle['ai_reasoning']}")
            if last_cycle.get("recommended_action"):
                lines.append(f"- Recommended action: {last_cycle['recommended_action']}")
            outcome = last_cycle.get("outcome")
            if isinstance(outcome, dict) and outcome.get("key_finding"):
                lines.append(f"- Last outcome: {outcome['key_finding']}")
            if isinstance(outcome, dict) and outcome.get("ai_reflection"):
                lines.append(f"- AI reflection: {outcome['ai_reflection']}")
        else:
            lines.append("- Last cycle: No cycles recorded yet")
        recent_runs = state.get("recent_runs") or []
        if recent_runs:
            lines.append("- Recent runs:")
            for run in recent_runs[-5:]:
                lines.append(
                    "  - "
                    f"{run.get('run_id', 'unknown')} [{run.get('mode', 'unknown')}] "
                    f"status={run.get('status', 'unknown')} errors={run.get('errors', 0)} "
                    f"contract={run.get('contract', 'unknown')}"
                )
        inbox = state.get("human_inbox") or []
        lines.append("- Human inbox:")
        if inbox:
            for item in inbox[-5:]:
                lines.append(f"  - {item}")
        else:
            lines.append("  - No pending human actions")
    return "\n".join(lines) + "\n"


def _render_budget_markdown(states: list[dict[str, Any]], *, generated_at: str) -> str:
    lines = ["# Loop Budget", "", f"Generated: {generated_at}"]
    if not states:
        lines.extend(["", "No loop profiles initialized."])
        return "\n".join(lines) + "\n"

    for state in states:
        budget = state.get("budget") or {}
        lines.extend([
            "",
            f"## {state.get('profile_id', 'unknown')}",
            f"- Budget policy ref: {state.get('budget_policy_ref') or 'n/a'}",
            f"- Daily cap tokens: {budget.get('daily_cap_tokens') if budget.get('daily_cap_tokens') is not None else 'n/a'}",
            f"- Weekly cap tokens: {budget.get('weekly_cap_tokens') if budget.get('weekly_cap_tokens') is not None else 'n/a'}",
            f"- Tokens spent today: {budget.get('spent_today_tokens', 0)}",
            f"- Tokens spent this week: {budget.get('spent_this_week_tokens', 0)}",
            f"- Budget last updated: {budget.get('last_updated', 'unknown')}",
        ])
    return "\n".join(lines) + "\n"


def _append_run_log(path: Path, profile_id: str, event: str, source_path: Path, timestamp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "# Loop Run Log\n\n" if not path.exists() else ""
    entry = f"- {timestamp} [{profile_id}] {event}: {source_path}\n"
    _append_text_atomic(path, prefix + entry)


def _loop_root(output_dir: Path) -> Path:
    return output_dir / "loops"


def _loop_state_path(profile_id: str, output_dir: Path) -> Path:
    safe_profile_id = profile_id.replace("/", "_").replace("\\", "_")
    return _loop_root(output_dir) / "state" / f"{safe_profile_id}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2, default=str) + "\n")


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

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


def _append_text_atomic(path: Path, text: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    _write_text_atomic(path, existing + text)
