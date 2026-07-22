from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

import pytest

from adaptive_synth_eval.adversarial_response_engine.core.models import JudgeVerdict
from adaptive_synth_eval.adversarial_response_engine.core.token_budget import (
    TokenBudgetManager,
)
from adaptive_synth_eval.unified_eval.config.contract import load_unified_contract
from adaptive_synth_eval.unified_eval.config.schemas import ComponentOverrides, LLMSpec
from adaptive_synth_eval.unified_eval.orchestrator.adversarial_runtime import (
    AdversarialRuntime,
)
from adaptive_synth_eval.unified_eval.orchestrator.memory_registry import (
    AttackMemoryRegistry,
)
from adaptive_synth_eval.unified_eval.providers.llm_factory import (
    ProvidedLLM,
    build_component_llms,
)
from adaptive_synth_eval.unified_eval.scoring.router import score_adversarial_turn

EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "examples"
    / "unified_evaluation_demo.yaml"
)


def test_runtime_is_conversation_scoped_and_applies_scenario_settings():
    contract = load_unified_contract(EXAMPLE)
    contract = replace(
        contract,
        llm=LLMSpec(provider="mock", model="mock"),
        components=ComponentOverrides(),
    )
    scenario = replace(
        contract.adversarial_scenario_catalog[0],
        failure_threshold=4,
        fresh_start_after_refusals=0,
    )
    llms = build_component_llms(contract)
    budget = TokenBudgetManager(10_000)

    first = AdversarialRuntime.build(
        contract=contract,
        llms=llms,
        token_budget=budget,
        meter=None,
        attack_memory=None,
        adv_scenario=scenario,
        rng=random.Random(1),
        session_id="c1",
        turn_count=3,
    )
    second = AdversarialRuntime.build(
        contract=contract,
        llms=llms,
        token_budget=budget,
        meter=None,
        attack_memory=None,
        adv_scenario=scenario,
        rng=random.Random(2),
        session_id="c2",
        turn_count=3,
    )

    assert first.attack_agent is not second.attack_agent
    assert first.judge is not second.judge
    assert first.attack_agent.rotate_after_refusals == 0
    assert first.session.failure_threshold == 4


def test_score_adversarial_turn_retains_every_typed_verdict_field():
    verdict = JudgeVerdict.from_dict(
        {
            "failure_score": 2,
            "refusal_quality": 1,
            "harm_potential": 3,
            "specificity": 4,
            "refusal_score": 1,
            "guardrail_worked": False,
            "near_miss": True,
            "confidence": 0.8,
            "failure_type": "tool-abuse",
            "short_reason": "short",
            "reasoning": "full",
            "trace_severity_score": 4,
            "overall_severity_score": 4,
            "trajectory_risk": "high",
            "failure_surface": "tool_call",
            "tool_call_risk_score": 4,
            "unsafe_delegation_score": 3,
            "instruction_priority_violation": True,
        }
    )

    class _Judge:
        def judge(self, *args, **kwargs):
            return verdict

    payload = score_adversarial_turn(
        judge=_Judge(),
        user_input="u",
        bot_response="b",
        trace_summary={"binding_actions": ["write"]},
    )

    expected = {
        "failure_score",
        "refusal_quality",
        "harm_potential",
        "specificity",
        "refusal_score",
        "guardrail_worked",
        "near_miss",
        "confidence",
        "failure_type",
        "short_reason",
        "reasoning",
        "judge_error",
        "trace_severity_score",
        "overall_severity_score",
        "trajectory_risk",
        "failure_surface",
        "tool_call_risk_score",
        "unsafe_delegation_score",
        "instruction_priority_violation",
        "_verdict",
    }
    assert expected <= payload.keys()


def test_attack_memory_registry_supports_shared_per_persona_and_none():
    shared = AttackMemoryRegistry(mode="shared", max_entries=10)
    per_persona = AttackMemoryRegistry(mode="per_persona", max_entries=10)
    disabled = AttackMemoryRegistry(mode="none", max_entries=10)

    assert shared.for_persona("P1") is shared.for_persona("P2")
    assert per_persona.for_persona("P1") is not per_persona.for_persona("P2")
    assert disabled.for_persona("P1") is None
    assert shared.to_dict()["mode"] == "shared"
    assert per_persona.to_dict()["mode"] == "per_persona"

    restored = AttackMemoryRegistry.from_dict(per_persona.to_dict())
    assert restored.mode == "per_persona"
    assert restored.for_persona("P1") is not restored.for_persona("P2")


def test_component_llms_build_policy_only_for_llm_policy_mode():
    contract = load_unified_contract(EXAMPLE)
    contract = replace(
        contract,
        llm=LLMSpec(provider="mock", model="mock"),
        components=ComponentOverrides(),
        run=replace(contract.run, session_policy="none"),
    )

    without_policy = build_component_llms(contract)
    with_policy = build_component_llms(
        replace(contract, run=replace(contract.run, session_policy="llm"))
    )

    assert "policy" not in without_policy
    assert "policy" in with_policy
    with pytest.raises(RuntimeError, match="synth interface"):
        without_policy["planner"].synth_chat("unused")
    with pytest.raises(RuntimeError, match="ARE interface"):
        without_policy["user_simulator"].call_fn(system="unused", user="unused")


def test_mock_provider_views_are_conversation_scoped_and_repeatable():
    contract = load_unified_contract(EXAMPLE)
    contract = replace(
        contract,
        llm=LLMSpec(provider="mock", model="mock"),
        components=ComponentOverrides(),
    )
    shared = build_component_llms(contract)

    first = {name: provided.for_conversation(1234) for name, provided in shared.items()}
    second = {
        name: provided.for_conversation(1234) for name, provided in shared.items()
    }

    first_synth = first["user_simulator"].synth_chat("prompt")
    first["user_simulator"].synth_chat("prompt")
    second_synth = second["user_simulator"].synth_chat("prompt")

    system = "You are a red-team strategist and adaptation planner."
    first_plan = first["planner"].call_fn(system=system, user="turn")
    first["planner"].call_fn(system=system, user="turn")
    second_plan = second["planner"].call_fn(system=system, user="turn")

    assert first_synth == second_synth
    assert first_plan == second_plan
    assert first["planner"] is not second["planner"]


def test_provided_llm_prepare_initializes_lazy_transport_once():
    calls: list[str] = []
    provided = ProvidedLLM(
        spec=LLMSpec(provider="mock", model="mock"),
        call_fn=lambda system, user: {"content": "{}", "usage": {}},
        synth_chat=lambda prompt: "ok",
        prepare_fn=lambda: calls.append("prepare"),
    )

    provided.prepare()
    provided.prepare()

    assert calls == ["prepare"]
