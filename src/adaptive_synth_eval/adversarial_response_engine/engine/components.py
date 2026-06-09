import json
from typing import Optional

from .prompts import (
    ADAPT_SYSTEM, ADAPT_USER_TEMPLATE,
    GENERATE_SYSTEM, GENERATE_USER_TEMPLATE,
    JUDGE_CONFIGS,
    SESSION_POLICY_SYSTEM, SESSION_POLICY_USER_TEMPLATE,
)
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
             style_hint: str = "") -> PlanResult:
        memory_ctx = attack_memory.to_context_str() if attack_memory else "No cross-session memory."
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
        )
        if style_hint:
            user += f"\n\nStyle directive: {style_hint}"
        return PlanResult.from_dict(self.llm.complete_json(ADAPT_SYSTEM, user))


class TurnGenerator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def generate(self, session: SessionState, strategy_instruction: str) -> GeneratedTurn:
        user = GENERATE_USER_TEMPLATE.format(
            scenario_type=session.scenario_type,
            scenario=session.scenario,
            strategy_instruction=strategy_instruction,
            history=_summarize_history(session),
        )
        return GeneratedTurn.from_dict(self.llm.complete_json(GENERATE_SYSTEM, user))


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
        return JudgeVerdict.from_dict(self.llm.complete_json(self._system, user))


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
