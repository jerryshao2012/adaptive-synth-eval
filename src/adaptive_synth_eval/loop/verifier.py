from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adaptive_synth_eval.loop.policy import LoopPolicyEngine, PolicyPlan
from adaptive_synth_eval.loop.profiles import LoopProfile


@dataclass(frozen=True)
class CheckerDecision:
    verdict: str
    reason: str
    approved_actions: list[str]
    rejected_actions: list[str]

    @property
    def approved(self) -> bool:
        return self.verdict == "approved"


class LoopVerifier:
    def __init__(self, profile: LoopProfile):
        self.profile = profile
        self.policy = LoopPolicyEngine(profile)

    def verify_plan(
            self,
            plan: PolicyPlan,
            *,
            loop_state: dict[str, Any] | None,
            target: dict[str, Any],
    ) -> CheckerDecision:
        if plan.denied:
            return CheckerDecision(
                verdict="rejected",
                reason=plan.deny_reason or "Target denied by policy.",
                approved_actions=[],
                rejected_actions=["target_execution"],
            )

        approved_actions: list[str] = []
        rejected_actions: list[str] = []
        max_retries = self.policy.max_retry_attempts()
        for action in plan.assisted_actions:
            if action.risk_class.lower() in {"high", "blocked"}:
                rejected_actions.append(action.action)
                continue

            key = self.policy.retry_key(target, action.action)
            attempts = self.policy.retry_attempts(loop_state, key)
            if attempts >= max_retries:
                rejected_actions.append(action.action)
                continue

            approved_actions.append(action.action)

        if rejected_actions:
            return CheckerDecision(
                verdict="rejected",
                reason=(
                    "Checker rejected one or more assisted actions: "
                    f"{', '.join(rejected_actions)}. "
                    f"max_retry_attempts={max_retries}."
                ),
                approved_actions=approved_actions,
                rejected_actions=rejected_actions,
            )

        return CheckerDecision(
            verdict="approved",
            reason="Checker approved target execution and assisted actions.",
            approved_actions=approved_actions,
            rejected_actions=[],
        )
