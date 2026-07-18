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


def score_adversarial_turn(
        *, judge, user_input: str, bot_response: str,
        scenario: str = "", history: str = "",
        trace_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """judge is an ARE SafetyJudge instance (sync); caller wraps in asyncio.to_thread.

    scenario/history feed the authorization-aware judge templates (data-pii-leak,
    document-exfiltration) so the judge can tell in-scope disclosure from an actual
    cross-boundary breach and catch data assembled across turns.

    trace_summary (trajectory mode only) makes the judge score the target's internal
    trajectory alongside the final response; when None, the judge is response-only.
    """
    verdict = judge.judge(
        user_input, bot_response, scenario=scenario, history=history,
        trace_summary=trace_summary,
    )
    payload = {
        "failure_score": verdict.failure_score,
        "refusal_quality": verdict.refusal_quality,
        "harm_potential": verdict.harm_potential,
        "specificity": verdict.specificity,
        "refusal_score": verdict.refusal_score,
        "guardrail_worked": verdict.guardrail_worked,
        "near_miss": verdict.near_miss,
        "confidence": verdict.confidence,
        "failure_type": verdict.failure_type,
        "short_reason": verdict.short_reason,
        "reasoning": verdict.reasoning,
        "judge_error": verdict.judge_error,
        "trace_severity_score": verdict.trace_severity_score,
        "overall_severity_score": verdict.overall_severity_score,
        "trajectory_risk": verdict.trajectory_risk,
        "failure_surface": verdict.failure_surface,
        "tool_call_risk_score": verdict.tool_call_risk_score,
        "unsafe_delegation_score": verdict.unsafe_delegation_score,
        "instruction_priority_violation": verdict.instruction_priority_violation,
        "_verdict": verdict,  # caller will pop before serialization
    }
    return payload
