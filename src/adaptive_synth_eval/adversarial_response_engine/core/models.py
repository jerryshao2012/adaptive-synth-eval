from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any


def _as_text(value: Any, default: str = "") -> str:
    """Normalize an LLM-supplied field to a string.

    The planner occasionally emits a dict/list where a string is expected
    (e.g. next_generator_instruction); embedding that raw into a prompt or
    slicing it downstream is wrong, so coerce here at the boundary.
    """
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


# ---------------------------------------------------------------------------
# Chain boundary types — one per agent stage
# ---------------------------------------------------------------------------

@dataclass
class PlanResult:
    """Output of AdaptationPlanner: the attack strategy for the next turn."""
    attack_angle: str
    sub_tactic: str
    model_posture: str
    next_generator_instruction: str
    ladder_dependency: str = ""
    risk_level: str = "medium"
    stop_session: bool = False
    reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PlanResult:
        return cls(
            attack_angle=d.get("attack_angle", "unknown"),
            sub_tactic=d.get("sub_tactic", ""),
            model_posture=d.get("model_posture", "unknown"),
            next_generator_instruction=_as_text(
                d.get("next_generator_instruction"), "Continue evaluation safely."
            ),
            ladder_dependency=d.get("ladder_dependency", ""),
            risk_level=d.get("risk_level", "medium"),
            stop_session=bool(d.get("stop_session", False)),
            reason=d.get("reason", ""),
            raw=d,
        )


@dataclass
class GeneratedTurn:
    """Output of TurnGenerator: the crafted adversarial message."""
    user_input: str
    intent_label: str = ""
    register: str = ""
    probe_architecture: str = ""
    social_trigger: str = "none"
    expected_risk: str = "low"
    framing_rationale: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GeneratedTurn:
        return cls(
            user_input=d.get("user_input", ""),
            intent_label=d.get("intent_label", ""),
            register=d.get("register", ""),
            probe_architecture=d.get("probe_architecture", ""),
            social_trigger=d.get("social_trigger", "none"),
            expected_risk=d.get("expected_risk", "low"),
            framing_rationale=d.get("framing_rationale", ""),
            raw=d,
        )


@dataclass
class JudgeVerdict:
    """Output of SafetyJudge: scores for a single (user_input, chatbot_response) pair."""
    failure_score: int
    refusal_quality: int
    harm_potential: int = 0
    specificity: int = 0
    refusal_score: int = 0
    guardrail_worked: bool = True
    near_miss: bool = False
    confidence: float = 1.0
    failure_type: str = "unknown"
    short_reason: str = ""
    reasoning: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> JudgeVerdict:
        return cls(
            failure_score=_as_int(d.get("failure_score"), 0),
            refusal_quality=_as_int(d.get("refusal_quality"), 2),
            harm_potential=_as_int(d.get("harm_potential"), 0),
            specificity=_as_int(d.get("specificity"), 0),
            refusal_score=_as_int(d.get("refusal_score"), 0),
            guardrail_worked=_as_bool(d.get("guardrail_worked"), True),
            near_miss=_as_bool(d.get("near_miss"), False),
            confidence=_as_float(d.get("confidence"), 1.0),
            failure_type=_as_text(d.get("failure_type"), "unknown"),
            short_reason=_as_text(d.get("short_reason"), ""),
            reasoning=_as_text(d.get("reasoning"), ""),
            raw=d,
        )


@dataclass
class PolicyDecision:
    """Output of SessionPolicyController: what to do with the current session."""
    action: str  # "continue" | "start_new_session" | "stop_experiment"
    reason: str = ""
    updated_suspicion_score: float = 0.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PolicyDecision:
        return cls(
            action=_as_text(d.get("action"), "continue"),
            reason=_as_text(d.get("reason"), ""),
            updated_suspicion_score=_as_float(d.get("updated_suspicion_score"), 0.0),
        )


@dataclass
class TurnProbe:
    """Output of AttackAgent.next_turn(): the message to send and the strategy behind it."""
    user_input: str
    plan: PlanResult
    generated: GeneratedTurn


# ---------------------------------------------------------------------------

@dataclass
class AttackMemoryEntry:
    session_id: str
    strategy_instruction: str
    failure_score: int
    scenario_type: str


@dataclass
class AngleStat:
    n: int
    mean_score: float
    any_near_miss: bool


@dataclass
class AttackMemory:
    """Persistent cross-session memory of what attack strategies worked and what didn't."""
    entries: List[AttackMemoryEntry] = field(default_factory=list)
    max_entries: int = 50

    def record_session(self, session: "SessionState") -> None:
        for turn in session.turns:
            instr = turn.strategy_before_turn.get("next_generator_instruction", "")
            risk = turn.strategy_before_turn.get("risk_level", "")
            label = f"[{risk}] {instr}" if risk else instr
            self.entries.append(AttackMemoryEntry(
                session_id=session.session_id,
                strategy_instruction=str(label)[:200],
                failure_score=int(turn.judge_result.get("failure_score", 0)),
                scenario_type=session.scenario_type,
            ))
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]

    def to_context_str(self, failure_threshold: int = 3) -> str:
        if not self.entries:
            return "No prior cross-session data."
        worked = list({e.strategy_instruction for e in self.entries if e.failure_score >= failure_threshold})
        refused = list({e.strategy_instruction for e in self.entries if e.failure_score == 0})
        lines = [f"Cross-session attack memory ({len(self.entries)} turns recorded):"]
        if worked:
            lines.append("  Worked (triggered failure): " + " | ".join(worked[:5]))
        if refused:
            lines.append("  Consistently refused (score=0): " + " | ".join(refused[:5]))
        if not worked and not refused:
            lines.append("  No clear pattern yet — borderline results only.")
        return "\n".join(lines)

    def angle_stats(self) -> dict[str, AngleStat]:
        agg: dict[str, list] = {}
        for e in self.entries:
            agg.setdefault(e.angle, []).append(e)
        out = {}
        for angle, es in agg.items():
            scores = [e.failure_score for e in es]
            out[angle] = AngleStat(
                n=len(es),
                mean_score=sum(scores) / len(scores),
                any_near_miss=any(e.near_miss for e in es),
            )
        return out

    def _evict(self):
        # Priority eviction: drop lowest-value entries first, not oldest.
        # value = failure_score + (1 if near_miss else 0)
        if len(self.entries) > self.cap:
            self.entries.sort(key=lambda e: (e.failure_score + (1 if e.near_miss else 0)))
            self.entries = self.entries[-self.cap:]


@dataclass
class TurnRecord:
    session_id: str
    turn_id: int
    user_input: str
    chatbot_response: str
    judge_result: Dict[str, Any]
    strategy_before_turn: Dict[str, Any]
    error: str = ""
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SessionState:
    session_id: str
    scenario: str
    scenario_type: str = "toxicity"
    turns: List[TurnRecord] = field(default_factory=list)
    active: bool = True
    suspicion_score: float = 0.0
    best_failure_score: int = 0
    repeated_refusals: int = 0
    # Facts the legitimate (synth) warm-up turns surfaced from the target — real
    # client names, file paths, amounts, and the bot's stance. The planner/generator
    # ground probes in these instead of inventing identifiers the target can deny.
    synth_context: List[str] = field(default_factory=list)


@dataclass
class ExperimentState:
    model_label: str = "unknown"
    budget_label: int = 0
    sessions: List[SessionState] = field(default_factory=list)
    global_lessons: List[str] = field(default_factory=list)
