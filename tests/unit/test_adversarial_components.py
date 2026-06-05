from __future__ import annotations

from adaptive_synth_eval.adversarial_response_engine.core.models import JudgeVerdict
from adaptive_synth_eval.adversarial_response_engine.core.token_budget import TokenBudgetManager
from adaptive_synth_eval.adversarial_response_engine.engine.attack_agent import AttackAgent
from adaptive_synth_eval.adversarial_response_engine.engine.components import SafetyJudge
from adaptive_synth_eval.unified_eval.personas.bridge import (
    HIJACK_TARGET_DEFAULTS,
    resolve_hijack_target,
)


def test_adversarial_imports_and_construct():
    """Verify that we can import and construct core classes of the adversarial engine."""
    manager = TokenBudgetManager(max_total_tokens=5000)
    assert manager.max_total_tokens == 5000
    assert manager.used_total_tokens == 0

    # Test the existence/import of the components
    assert AttackAgent is not None
    assert SafetyJudge is not None


def test_resolve_hijack_target_uses_override():
    assert resolve_hijack_target(
        "persona-hijack", "a sworn judge advising the bench"
    ) == "a sworn judge advising the bench"


def test_resolve_hijack_target_falls_back_to_default_for_persona_hijack():
    assert resolve_hijack_target("persona-hijack", None) == HIJACK_TARGET_DEFAULTS["persona-hijack"]


def test_resolve_hijack_target_empty_for_other_scenarios():
    assert resolve_hijack_target("toxicity", None) == ""
    assert resolve_hijack_target("prompt-injection", None) == ""
    assert resolve_hijack_target("data-pii-leak", None) == ""


def test_judge_verdict_from_dict_handles_null_values():
    verdict = JudgeVerdict.from_dict({
        "failure_score": None,
        "refusal_quality": None,
        "harm_potential": "bad-int",
        "specificity": None,
        "refusal_score": None,
        "guardrail_worked": None,
        "near_miss": None,
        "confidence": None,
        "failure_type": None,
        "short_reason": None,
        "reasoning": None,
    })

    assert verdict.failure_score == 0
    assert verdict.refusal_quality == 2
    assert verdict.harm_potential == 0
    assert verdict.specificity == 0
    assert verdict.refusal_score == 0
    assert verdict.guardrail_worked is True
    assert verdict.near_miss is False
    assert verdict.confidence == 1.0
    assert verdict.failure_type == "unknown"
