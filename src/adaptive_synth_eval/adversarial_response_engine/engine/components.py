import json
from typing import Any, Dict, Optional

from .prompts import (
    ADAPT_SYSTEM, ADAPT_USER_TEMPLATE,
    GENERATE_SYSTEM, GENERATE_USER_TEMPLATE,
    JUDGE_CONFIGS,
    JUDGE_TRAJECTORY_GUIDANCE, JUDGE_TRAJECTORY_USER_APPENDIX,
    SESSION_POLICY_SYSTEM, SESSION_POLICY_USER_TEMPLATE,
    TRACE_SUMMARIZER_SYSTEM, TRACE_SUMMARIZER_USER_TEMPLATE,
)
from .taxonomy import render_angle_detail, scenario_strategy_note
from ..core.models import (
    SessionState, AttackMemory,
    PlanResult, GeneratedTurn, JudgeVerdict, PolicyDecision,
)
from ..providers.llm_client import LLMClient


def _clip(value, limit: int) -> str:
    """Coerce any planner/judge field to a string before slicing.

    These fields are usually strings, but the planner LLM sometimes emits a
    structured object (e.g. next_generator_instruction as a dict). Slicing a
    dict/list with [:limit] raises `KeyError: slice(...)`, so normalize first.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value)
    return value[:limit]


def _summarize_history(session: SessionState, max_turns: int = 5) -> str:
    # tried_angles: ALL turns deduplicated by (angle, sub_tactic), highest score kept.
    # Gives the planner a fast scan of exhausted approaches without re-reading every turn.
    seen: dict = {}
    for t in session.turns:
        angle = t.strategy_before_turn.get("attack_angle", "unknown")
        sub = t.strategy_before_turn.get("sub_tactic", "")
        score = int(t.judge_result.get("failure_score", 0))
        key = (angle, sub)
        if key not in seen or score > seen[key]["score"]:
            seen[key] = {"angle": angle, "sub_tactic": sub, "score": score}
    tried = list(seen.values())

    # Per-turn records: compact operator-style log (technique + defense signal only).
    # Full user_input prose and bulk judge fields are dropped — they are reporting
    # artifacts, not planning signals. reasoning[:200] gives the key refusal trigger.
    recent = session.turns[-max_turns:]
    turns = []
    for t in recent:
        s = t.strategy_before_turn
        j = t.judge_result
        turns.append({
            "t": t.turn_id,
            "attack": {
                "angle": s.get("attack_angle"),
                "sub_tactic": s.get("sub_tactic"),
                "instruction": _clip(s.get("next_generator_instruction"), 150),
                "ladder": s.get("ladder_dependency", ""),
            },
            "defense": {
                "score": int(j.get("failure_score", 0)),
                "refusal_quality": int(j.get("refusal_quality", 2)),
                "type": j.get("failure_type", "unknown"),
                "near_miss": bool(j.get("near_miss", False)),
                "signal": _clip(j.get("reasoning"), 200),
            },
            "response_excerpt": _clip(t.chatbot_response, 200),
        })

    # Facts the legit warm-up turns surfaced (real client/file/amount) — the planner
    # and generator ground probes in these instead of inventing identifiers.
    synth_context = getattr(session, "synth_context", []) or []
    return json.dumps(
        {
            "synth_warmup_context": synth_context[-3:],
            "tried_angles": tried,
            "turns": turns,
        },
        indent=2,
    )


def _recent_dialogue(session: SessionState, n: int = 2) -> str:
    """Lean continuity context for the GENERATOR — just the last `n` raw turns.

    The generator does not need the planner's analytical history (tried angles,
    defense scores); the strategy is already in next_generator_instruction. It only
    needs enough recent dialogue to write a natural continuation that references what
    the bot just said. Keeping this minimal avoids double-processing history and the
    token cost of feeding the full analysis to both LLMs.
    """
    parts: list[str] = []
    warm = session.synth_context or []
    if warm and not session.turns:
        # No adversarial turns yet — the warm-up disclosures are the only real context.
        parts.append("Warm-up context the agent already revealed:")
        parts.extend(warm[-2:])
    for t in session.turns[-n:]:
        parts.append(f"user: {_clip(t.user_input, 300)}")
        parts.append(f"chatbot: {_clip(t.chatbot_response, 400)}")
    return "\n".join(parts) if parts else "(no prior turns in this conversation yet)"


def render_judge_history(session: SessionState, max_turns: int = 5) -> str:
    """Prior-conversation context for the authorization-aware judge.

    Combines warm-up disclosures (what the agent already, authorizedly, revealed) with
    the prior adversarial turns, so the judge can (a) recognize in-scope data as
    authorized and (b) detect a record assembled field-by-field across turns (see
    ACCUMULATION_ANGLES in taxonomy.py). Only adversarial turns live in session.turns;
    warm-up facts live in session.synth_context. At judge time session.turns holds only
    the turns BEFORE the current one, so this is purely prior context.
    """
    parts: list[str] = []
    warm = session.synth_context or []
    if warm:
        parts.append("Warm-up disclosures (authorized context the agent already revealed):")
        parts.extend(warm[-3:])
    prior = session.turns[-max_turns:]
    if prior:
        parts.append("Prior adversarial turns:")
        for t in prior:
            parts.append(f"[turn {t.turn_id}] user: {_clip(t.user_input, 300)}")
            parts.append(f"[turn {t.turn_id}] chatbot: {_clip(t.chatbot_response, 400)}")
    return "\n".join(parts) if parts else "(no prior turns in this conversation yet)"


class AdaptationPlanner:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def plan(self, session: SessionState, attack_memory: Optional[AttackMemory] = None, target_persona: str = "",
             style_hint: str = "", fixed_angle: str = "") -> PlanResult:
        memory_ctx = (
            attack_memory.to_context_str(session.failure_threshold)
            if attack_memory else "No cross-session memory."
        )
        user = ADAPT_USER_TEMPLATE.format(
            scenario_type=session.scenario_type,
            scenario=session.scenario,
            target_persona=target_persona or "(not applicable)",
            attack_memory=memory_ctx,
            history=_summarize_history(session),
            best_failure_score=session.best_failure_score,
            repeated_refusals=session.repeated_refusals,
            suspicion_score=session.suspicion_score,
            turn_count=len(session.turns),
            fixed_angle=fixed_angle or "(none assigned)",
            fixed_angle_detail=render_angle_detail(fixed_angle) if fixed_angle else "(none assigned)",
            scenario_note=scenario_strategy_note(session.scenario_type) or "(no scenario-specific note)",
        )
        if style_hint:
            user += f"\n\nStyle directive: {style_hint}"
        return PlanResult.from_dict(self.llm.complete_json(ADAPT_SYSTEM, user))


class TurnGenerator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def generate(self, session: SessionState, strategy_instruction: str,
                 variation_seed: str = "") -> GeneratedTurn:
        user = GENERATE_USER_TEMPLATE.format(
            scenario_type=session.scenario_type,
            scenario=session.scenario,
            strategy_instruction=strategy_instruction,
            history=_recent_dialogue(session),
            variation_seed=variation_seed or "(no preference — choose naturally)",
        )
        return GeneratedTurn.from_dict(self.llm.complete_json(GENERATE_SYSTEM, user))


class TraceSummarizer:
    """Compresses a normalized multi-agent execution trace into judge-ready facts.

    Used only in trajectory mode. The summary is fed to SafetyJudge.judge() so the
    judge can score the internal trajectory, not just the final response.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def summarize(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        # Cap the serialized trace so a huge raw_trace can't blow the prompt budget.
        trace_json = json.dumps(trace, default=str, indent=2)[:12000]
        user = TRACE_SUMMARIZER_USER_TEMPLATE.format(trace_json=trace_json)
        return self.llm.complete_json(TRACE_SUMMARIZER_SYSTEM, user)


class SafetyJudge:
    def __init__(self, llm: LLMClient, scenario_type: str = "toxicity"):
        self.llm = llm
        cfg = JUDGE_CONFIGS.get(scenario_type, JUDGE_CONFIGS["toxicity"])
        self._system = cfg["system"]
        self._user_template = cfg["user_template"]

    def judge(
            self,
            user_input: str,
            chatbot_response: str,
            scenario: str = "",
            history: str = "",
            trace_summary: Optional[Dict[str, Any]] = None,
    ) -> JudgeVerdict:
        # scenario/history are optional and only consumed by judge templates that
        # reference them (data-pii-leak, document-exfiltration). str.format ignores
        # unused kwargs, so the other scenario judges are unaffected.
        user = self._user_template.format(
            user_input=user_input,
            chatbot_response=chatbot_response,
            scenario=scenario or "(no scenario authorization boundary provided)",
            history=history or "(single-turn evaluation — no prior conversation supplied)",
        )
        system = self._system
        # Trajectory mode: extend the judge to score the internal trajectory too. When no
        # trace_summary is supplied, the prompt is byte-for-byte the response-only judge.
        if trace_summary is not None:
            system = system + "\n\n" + JUDGE_TRAJECTORY_GUIDANCE
            user = user + JUDGE_TRAJECTORY_USER_APPENDIX.format(
                trace_summary=json.dumps(trace_summary, default=str, indent=2)
            )
        result = self.llm.complete_json(system, user)
        # A judge that fails to return a usable verdict (parse error, or salvaged output
        # truncated before the score) must not be silently treated as a SAFE 0. Retry once
        # with a stricter, compact reminder before falling back to a judge_error verdict.
        if "error" in result or "failure_score" not in result:
            retry_user = user + (
                "\n\nIMPORTANT: Return ONLY a single compact JSON object — scores FIRST, "
                "reasoning <= 60 words LAST. Do not write multi-paragraph analysis."
            )
            result = self.llm.complete_json(system, retry_user)
        return JudgeVerdict.from_dict(result)


class SessionPolicyController:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def decide(self, session: SessionState) -> PolicyDecision:
        recent_judges = [t.judge_result for t in session.turns[-5:]]
        user = SESSION_POLICY_USER_TEMPLATE.format(
            session_state=json.dumps(
                {
                    "session_id": session.session_id,
                    "scenario_type": session.scenario_type,
                    "turn_count": len(session.turns),
                    "best_failure_score": session.best_failure_score,
                    "repeated_refusals": session.repeated_refusals,
                    "suspicion_score": session.suspicion_score,
                },
                indent=2,
            ),
            judge_results=json.dumps(recent_judges, indent=2),
        )
        return PolicyDecision.from_dict(self.llm.complete_json(SESSION_POLICY_SYSTEM, user))


from .config import PolicyConfig


class RuleBasedSessionPolicyController:
    def __init__(self, cfg: PolicyConfig):
        self.cfg = cfg

    def decide(self, session: SessionState) -> PolicyDecision:
        c = self.cfg
        last_was_refusal = session.turns and session.turns[-1].judge_result.get("failure_score", 0) == 0
        if last_was_refusal:
            new_susp = min(1.0, session.suspicion_score + c.suspicion_per_refusal)
        else:
            new_susp = max(0.0, session.suspicion_score - c.suspicion_decay)

        if session.repeated_refusals >= c.max_refusals:
            action, reason = "start_new_session", f"refusals>={c.max_refusals}"
        elif new_susp >= c.abandon_suspicion:
            action, reason = "start_new_session", f"suspicion>={c.abandon_suspicion}"
        elif (
                session.max_turns is not None
                and len(session.turns) >= session.max_turns
                and session.best_failure_score == 0
        ):
            action, reason = "start_new_session", "exhausted_no_signal"  # 1.6
        else:
            action, reason = "continue", "within thresholds"
        return PolicyDecision(action=action, reason=reason,
                              updated_suspicion_score=new_susp)
