from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from adaptive_synth_eval.artifacts.run_state import detect_incomplete_run
from adaptive_synth_eval.loop.profiles import LoopProfile


@dataclass(frozen=True)
class AssistedAction:
    action: str
    risk_class: str
    reason: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PolicyPlan:
    denied: bool
    deny_reason: str | None
    incomplete_run_action: str
    max_concurrency_override: int | None
    assisted_actions: list[AssistedAction]


class LoopPolicyEngine:
    def __init__(self, profile: LoopProfile):
        self.profile = profile
        self.checker_policy = dict(profile.checker_policy or {})

    def plan_target(
            self,
            *,
            loop_state: dict[str, Any] | None,
            target: dict[str, Any],
            mode_name: str,
            run_dir: Path | None,
            default_incomplete_run_action: str,
            max_concurrency: int | None,
    ) -> PolicyPlan:
        denied, deny_reason = self._is_denied(target)
        actions: list[AssistedAction] = []
        incomplete_action = default_incomplete_run_action
        max_concurrency_override = None

        if self.profile.readiness_level in {"L2", "L3"} and not denied:
            incomplete = detect_incomplete_run(run_dir) if run_dir is not None else None
            if incomplete is not None and self._enabled("allow_auto_resume", default=True):
                incomplete_action = "resume"
                actions.append(
                    AssistedAction(
                        action="auto_resume_incomplete",
                        risk_class="low",
                        reason="Detected an incomplete run directory and policy allows safe resume.",
                        metadata={"reason": incomplete.get("reason"), "run_dir": str(run_dir)},
                    )
                )

            if self._should_restart_stale_failed(loop_state=loop_state, target=target):
                incomplete_action = "restart"
                actions.append(
                    AssistedAction(
                        action="auto_restart_stale_failed",
                        risk_class="medium",
                        reason="Recent stale failed run detected and bounded retry policy allows restart.",
                        metadata={"contract": target.get("contract")},
                    )
                )

            if mode_name == "unified" and max_concurrency is not None:
                cap = self._int_policy("safe_max_concurrency")
                if cap is not None and cap > 0 and max_concurrency > cap:
                    max_concurrency_override = cap
                    actions.append(
                        AssistedAction(
                            action="apply_concurrency_cap",
                            risk_class="low",
                            reason="Applying checker policy safe_max_concurrency cap.",
                            metadata={"from": max_concurrency, "to": cap},
                        )
                    )

            if run_dir is not None and self._is_summary_missing(run_dir):
                actions.append(
                    AssistedAction(
                        action="regenerate_missing_summary",
                        risk_class="low",
                        reason="run_summary.json is missing while run artifacts exist.",
                        metadata={"run_dir": str(run_dir)},
                    )
                )

        return PolicyPlan(
            denied=denied,
            deny_reason=deny_reason,
            incomplete_run_action=incomplete_action,
            max_concurrency_override=max_concurrency_override,
            assisted_actions=actions,
        )

    def max_retry_attempts(self) -> int:
        retries = self._int_policy("max_retry_attempts")
        if retries is None:
            return 2
        return max(1, retries)

    def retry_key(self, target: dict[str, Any], action: str) -> str:
        return f"{target.get('contract', 'unknown')}::{action}"

    def retry_attempts(self, loop_state: dict[str, Any] | None, key: str) -> int:
        attempts = ((loop_state or {}).get("assisted_action_attempts") or {}).get(key)
        try:
            return int(attempts or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def summarize_actions(actions: list[AssistedAction], *, status: str) -> list[dict[str, Any]]:
        return [
            {
                "action": action.action,
                "risk_class": action.risk_class,
                "reason": action.reason,
                "status": status,
                "metadata": dict(action.metadata),
            }
            for action in actions
        ]

    def _is_denied(self, target: dict[str, Any]) -> tuple[bool, str | None]:
        haystack = json.dumps(target, sort_keys=True).lower()
        for token in self.profile.denylist:
            marker = str(token).strip().lower()
            if marker and marker in haystack:
                return True, f"Target matched denylist marker: {token}"
        return False, None

    def _should_restart_stale_failed(self, *, loop_state: dict[str, Any] | None, target: dict[str, Any]) -> bool:
        if not self._enabled("allow_auto_restart_stale_failed", default=True):
            return False

        stale_after_minutes = self._int_policy("stale_failed_restart_after_minutes")
        if stale_after_minutes is None:
            stale_after_minutes = 60

        contract = str(target.get("contract") or "").strip()
        if not contract:
            return False

        recent_runs = list((loop_state or {}).get("recent_runs") or [])
        for run in reversed(recent_runs):
            if str(run.get("contract") or "") != contract:
                continue
            status = str(run.get("status") or "")
            if status != "completed_with_errors":
                return False
            when = _parse_timestamp(run.get("timestamp"))
            if when is None:
                return True
            return when <= datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)
        return False

    def _enabled(self, key: str, *, default: bool) -> bool:
        if key not in self.checker_policy:
            return default
        return bool(self.checker_policy.get(key))

    def _int_policy(self, key: str) -> int | None:
        value = self.checker_policy.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_summary_missing(run_dir: Path) -> bool:
        if not run_dir.exists():
            return False
        summary_path = run_dir / "run_summary.json"
        if summary_path.exists():
            return False
        candidate_artifacts = (
            "run_state.json",
            "chat_history.jsonl",
            "conversations.jsonl",
            "turns.jsonl",
            "scores.jsonl",
        )
        return any((run_dir / name).exists() for name in candidate_artifacts)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
