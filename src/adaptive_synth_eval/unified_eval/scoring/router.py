"""Per-turn scoring dispatcher.

Synth turns -> ASE response_quality (heuristic, no LLM).
Adversarial turns -> ARE SafetyJudge (LLM call).
"""
from __future__ import annotations

from typing import Any

from adaptive_synth_eval.scoring.response_quality import score_response


def score_synth_turn(
        *,
        user_message: str,
        bot_response: str,
        expected_context: str | None,
        missing_context_expected: bool,
) -> dict[str, Any]:
    score = score_response(
        user_message=user_message,
        bot_response=bot_response,
        expected_context=expected_context,
        missing_context_expected=missing_context_expected,
    )
    return {
        "groundedness_score": score.groundedness_score,
        "relevance_score": score.relevance_score,
        "safety_score": score.safety_score,
        "clarification_score": score.clarification_score,
    }


def score_adversarial_turn(*, judge, user_input: str, bot_response: str) -> dict[str, Any]:
    """judge is an ARE SafetyJudge instance (sync); caller wraps in asyncio.to_thread."""
    verdict = judge.judge(user_input, bot_response)
    return {
        "failure_score": verdict.failure_score,
        "harm_potential": verdict.harm_potential,
        "specificity": verdict.specificity,
        "refusal_quality": verdict.refusal_quality,
        "refusal_score": verdict.refusal_score,
        "guardrail_worked": verdict.guardrail_worked,
        "near_miss": verdict.near_miss,
        "failure_type": verdict.failure_type,
        "short_reason": verdict.short_reason,
        "_verdict": verdict,  # caller will pop before serialization
    }
