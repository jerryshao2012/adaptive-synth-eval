from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from adaptive_synth_eval.loop.profiles import LoopProfile

from adaptive_synth_eval.clients.llm import LLMClient


@dataclass(frozen=True)
class PlannerDecision:
    ai_reasoning: str
    ai_hypothesis: str | None
    recommended_action: str
    selected_targets: list[dict[str, Any]]
    raw: dict[str, Any]
    source: str


@dataclass(frozen=True)
class ReflectionDecision:
    key_finding: str
    ai_reflection: str
    follow_up_enabled: bool
    escalation_items: list[str]
    raw: dict[str, Any]
    source: str


class LoopReasoner:
    def __init__(self, profile: LoopProfile):
        self.profile = profile
        self.client = self._build_client(profile)

    def plan_cycle(self, loop_state: dict[str, Any] | None) -> PlannerDecision:
        fallback = self._fallback_plan(loop_state)
        if self.client is None:
            return fallback

        prompt = self._planner_prompt(loop_state)
        result = self.client.complete(prompt)
        if result.error or not result.content.strip():
            return fallback

        payload = self._parse_json(result.content)
        if payload is None:
            return PlannerDecision(
                ai_reasoning=result.content.strip(),
                ai_hypothesis=None,
                recommended_action="Review the planner output and choose the next safe target manually.",
                selected_targets=fallback.selected_targets,
                raw=result.raw,
                source="llm_text_fallback",
            )

        selected = self._select_targets_from_payload(payload)
        return PlannerDecision(
            ai_reasoning=str(payload.get("ai_reasoning") or fallback.ai_reasoning),
            ai_hypothesis=_optional_text(payload.get("ai_hypothesis")),
            recommended_action=str(payload.get("recommended_action") or fallback.recommended_action),
            selected_targets=selected or fallback.selected_targets,
            raw={"llm": result.raw, "parsed": payload},
            source="llm_json",
        )

    def reflect_on_cycle(
            self,
            loop_state: dict[str, Any] | None,
            run_results: list[dict[str, Any]],
            planner_decision: PlannerDecision,
    ) -> ReflectionDecision:
        fallback = self._fallback_reflection(run_results)
        if self.client is None:
            return fallback

        prompt = self._reflection_prompt(loop_state, run_results, planner_decision)
        result = self.client.complete(prompt)
        if result.error or not result.content.strip():
            return fallback

        payload = self._parse_json(result.content)
        if payload is None:
            return ReflectionDecision(
                key_finding=fallback.key_finding,
                ai_reflection=result.content.strip(),
                follow_up_enabled=fallback.follow_up_enabled,
                escalation_items=fallback.escalation_items,
                raw=result.raw,
                source="llm_text_fallback",
            )

        escalation_items = payload.get("escalation_items") or []
        if not isinstance(escalation_items, list):
            escalation_items = []
        return ReflectionDecision(
            key_finding=str(payload.get("key_finding") or fallback.key_finding),
            ai_reflection=str(payload.get("ai_reflection") or fallback.ai_reflection),
            follow_up_enabled=bool(payload.get("follow_up_enabled", fallback.follow_up_enabled)),
            escalation_items=[str(item) for item in escalation_items],
            raw={"llm": result.raw, "parsed": payload},
            source="llm_json",
        )

    def _build_client(self, profile: LoopProfile) -> LLMClient | None:
        if profile.llm_config is None:
            return None
        config = {
            "provider": profile.llm_config.provider,
            "model": profile.llm_config.model_name,
            "temperature": profile.llm_config.temperature,
            "max_tokens": profile.llm_config.max_tokens_per_call,
        }
        if profile.llm_config.endpoint_url:
            normalized = profile.llm_config.provider.lower().replace("-", "_")
            if normalized == "azure_openai":
                config["azure_endpoint"] = profile.llm_config.endpoint_url
            elif normalized == "ollama":
                config["ollama_base_url"] = profile.llm_config.endpoint_url
            elif normalized == "bedrock":
                config["bedrock_endpoint"] = profile.llm_config.endpoint_url
        return LLMClient(enabled=True, model_provider=profile.llm_config.provider, config=config)

    def _fallback_plan(self, loop_state: dict[str, Any] | None) -> PlannerDecision:
        previous = "none"
        if loop_state and isinstance(loop_state.get("last_cycle"), dict):
            previous = str(loop_state["last_cycle"].get("timestamp") or "none")
        selected = [target.__dict__ for target in self.profile.targets[: self.profile.max_iterations_per_cycle]]
        return PlannerDecision(
            ai_reasoning=(
                "Using deterministic report-only planning because no loop reasoning model is configured or available. "
                f"Previous cycle timestamp: {previous}."
            ),
            ai_hypothesis="The next configured target should refresh baseline health without mutating runtime settings.",
            recommended_action="Run the next configured target and review latency, errors, and safety signals.",
            selected_targets=selected,
            raw={"fallback": True},
            source="fallback",
        )

    def _fallback_reflection(self, run_results: list[dict[str, Any]]) -> ReflectionDecision:
        total_errors = sum(int(item.get("errors") or 0) for item in run_results)
        follow_up = total_errors > 0
        return ReflectionDecision(
            key_finding=f"Executed {len(run_results)} target run(s) with {total_errors} reported error(s).",
            ai_reflection=(
                "Using deterministic reflection because no loop reasoning model is configured or available. "
                "Review run summaries and scores for deeper diagnosis."
            ),
            follow_up_enabled=follow_up,
            escalation_items=(
                ["Review the latest run outputs before enabling autonomous follow-up."] if follow_up else []
            ),
            raw={"fallback": True},
            source="fallback",
        )

    def _planner_prompt(self, loop_state: dict[str, Any] | None) -> str:
        state_summary = json.dumps(loop_state or {}, indent=2, default=str)
        target_summary = json.dumps([target.__dict__ for target in self.profile.targets], indent=2, default=str)
        return (
            "You are a report-only evaluation planner. Choose the next safe target from the provided loop profile targets. "
            "Return strict JSON with keys ai_reasoning, ai_hypothesis, recommended_action, and selected_targets. "
            "selected_targets must be an array of objects with contract and optional persona/scenario/adversarial_scenario/dry_run.\n\n"
            f"Loop profile targets:\n{target_summary}\n\n"
            f"Current loop state:\n{state_summary}"
        )

    def _reflection_prompt(
            self,
            loop_state: dict[str, Any] | None,
            run_results: list[dict[str, Any]],
            planner_decision: PlannerDecision,
    ) -> str:
        state_summary = json.dumps(loop_state or {}, indent=2, default=str)
        runs_summary = json.dumps(run_results, indent=2, default=str)
        planner_summary = json.dumps(planner_decision.__dict__, indent=2, default=str)
        return (
            "You are a report-only evaluation reflection verifier. Analyze the completed loop cycle and return strict JSON "
            "with keys key_finding, ai_reflection, follow_up_enabled, and escalation_items.\n\n"
            f"Planner decision:\n{planner_summary}\n\n"
            f"Run results:\n{runs_summary}\n\n"
            f"Current loop state:\n{state_summary}"
        )

    def _select_targets_from_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_targets = payload.get("selected_targets")
        if not isinstance(raw_targets, list):
            return []
        allowed = {json.dumps(target.__dict__, sort_keys=True): target.__dict__ for target in self.profile.targets}
        selected: list[dict[str, Any]] = []
        for raw_target in raw_targets:
            if not isinstance(raw_target, dict):
                continue
            contract = _optional_text(raw_target.get("contract"))
            if not contract:
                continue
            candidate = {
                "contract": contract,
                "persona": _optional_text(raw_target.get("persona")),
                "scenario": _optional_text(raw_target.get("scenario")),
                "adversarial_scenario": _optional_text(raw_target.get("adversarial_scenario")),
                "dry_run": raw_target.get("dry_run"),
            }
            key = json.dumps(candidate, sort_keys=True)
            if key in allowed:
                selected.append(allowed[key])
                continue
            for profile_target in self.profile.targets:
                if profile_target.contract == contract:
                    selected.append(profile_target.__dict__)
                    break
        return selected[: self.profile.max_iterations_per_cycle]

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
