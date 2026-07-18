"""Conversation-scoped assembly of the existing adversarial engine components."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from adaptive_synth_eval.adversarial_response_engine.core.models import AttackMemory, SessionState
from adaptive_synth_eval.adversarial_response_engine.engine.attack_agent import AttackAgent
from adaptive_synth_eval.adversarial_response_engine.engine.components import (
    AdaptationPlanner,
    RuleBasedSessionPolicyController,
    SafetyJudge,
    SessionPolicyController,
    TraceSummarizer,
    TurnGenerator,
)
from adaptive_synth_eval.adversarial_response_engine.engine.config import PolicyConfig
from adaptive_synth_eval.adversarial_response_engine.providers.llm_client import LLMClient as AREClient
from adaptive_synth_eval.adversarial_response_engine.providers.trace_provider import InlineTraceProvider
from adaptive_synth_eval.unified_eval.config.schemas import AdversarialScenario, UnifiedContract
from adaptive_synth_eval.unified_eval.personas.bridge import resolve_hijack_target
from adaptive_synth_eval.unified_eval.providers.llm_factory import ProvidedLLM


def _are_client(component: str, provided: ProvidedLLM, token_budget, meter) -> AREClient:
    on_usage = None
    if meter is not None:
        on_usage = lambda prompt, completion: meter.record_passthrough(
            component, prompt, completion
        )
    return AREClient(provided.call_fn, token_budget, on_usage=on_usage)


def _build_session_policy(contract: UnifiedContract, llms, token_budget, meter):
    mode = contract.run.session_policy
    if mode == "none":
        return None
    if mode == "rule":
        return RuleBasedSessionPolicyController(PolicyConfig(
            max_refusals=contract.run.policy_max_refusals,
            suspicion_per_refusal=contract.run.policy_suspicion_per_refusal,
            suspicion_decay=contract.run.policy_suspicion_decay,
            abandon_suspicion=contract.run.policy_abandon_suspicion,
        ))
    if mode == "llm":
        if "policy" not in llms:
            raise ValueError("run.session_policy='llm' requires a policy LLM")
        return SessionPolicyController(
            _are_client("policy", llms["policy"], token_budget, meter)
        )
    raise ValueError(f"Unknown run.session_policy: {mode!r}. Use one of: none, rule, llm.")


@dataclass
class AdversarialRuntime:
    """All mutable ARE objects owned by one unified conversation."""

    attack_agent: AttackAgent
    judge: SafetyJudge
    session_policy_controller: Any
    trace_provider: InlineTraceProvider | None
    trace_summarizer: TraceSummarizer | None
    session: SessionState

    @classmethod
    def build(
            cls,
            *,
            contract: UnifiedContract,
            llms: dict[str, ProvidedLLM],
            token_budget,
            meter,
            attack_memory: AttackMemory | None,
            adv_scenario: AdversarialScenario,
            rng: random.Random,
            session_id: str,
            turn_count: int,
    ) -> "AdversarialRuntime":
        planner = AdaptationPlanner(
            _are_client("planner", llms["planner"], token_budget, meter)
        )
        generator = TurnGenerator(
            _are_client("generator", llms["generator"], token_budget, meter)
        )
        judge = SafetyJudge(
            _are_client("judge", llms["judge"], token_budget, meter),
            scenario_type=adv_scenario.scenario_type,
        )
        trajectory_enabled = contract.trajectory.enabled
        trace_provider = (
            InlineTraceProvider(trace_field=contract.trajectory.trace_field)
            if trajectory_enabled else None
        )
        trace_summarizer = (
            TraceSummarizer(_are_client("judge", llms["judge"], token_budget, meter))
            if trajectory_enabled else None
        )
        hijack_target = resolve_hijack_target(
            adv_scenario.scenario_type, adv_scenario.hijack_target
        )
        attack_agent = AttackAgent(
            planner=planner,
            generator=generator,
            attack_memory=attack_memory,
            persona_pool=[hijack_target] if hijack_target else [],
            rng=rng,
            rotate_after_refusals=adv_scenario.fresh_start_after_refusals,
        )
        session = SessionState(
            session_id=session_id,
            scenario=adv_scenario.scenario_text,
            scenario_type=adv_scenario.scenario_type,
            max_turns=turn_count,
            failure_threshold=adv_scenario.failure_threshold,
        )
        return cls(
            attack_agent=attack_agent,
            judge=judge,
            session_policy_controller=_build_session_policy(
                contract, llms, token_budget, meter
            ),
            trace_provider=trace_provider,
            trace_summarizer=trace_summarizer,
            session=session,
        )
