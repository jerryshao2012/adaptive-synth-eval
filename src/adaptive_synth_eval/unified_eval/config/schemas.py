"""Unified contract schema. Reuses ASE Persona/Scenario dataclasses verbatim."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from adaptive_synth_eval.config.schemas import (
    ConversationTurns,
    OutputConfig,
    Persona,
    Scenario,
    TargetChatbot,
    TimeWindow,
)


@dataclass(frozen=True)
class Suite:
    suite_id: str
    target_application: str
    run_mode: str = "unified"
    synthetic_flag: bool = True


@dataclass(frozen=True)
class RunSettings:
    run_id: str | None = None
    random_seed: int | None = None
    max_concurrency: int = 5
    dry_run: bool = False
    verbose: bool = False
    budget: int = 200_000
    reserve_tokens: int = 1500
    # When true: ignore eval_plan.total_conversations and keep launching conversations
    # (drawn lazily from eval_plan.entries by weight) until the token budget is exhausted.
    # Runs sequentially regardless of max_concurrency for clean budget bookkeeping.
    until_budget_exhausted: bool = False
    # Safety cap to prevent runaway loops when until_budget_exhausted is true and
    # something stops consuming tokens (e.g. mock backend with near-zero cost).
    max_conversations_safety_cap: int = 1000
    # Retry behavior for transient LLM API failures (429, 500, timeout).
    retry_max_attempts: int = 3
    retry_initial_backoff_seconds: float = 1.0
    retry_max_backoff_seconds: float = 30.0
    # ARE-style session policy applied to adversarial turns. After each adversarial
    # turn the controller decides whether to continue or abandon the conversation.
    # When it says "abandon", the conversation ends early — saving budget for the
    # next conversation in the run.
    #   "none" (default): no session control; conversation runs to its turn count
    #   "rule":           rule-based (uses RuleBasedSessionPolicyController + PolicyConfig)
    #   "llm":            LLM-based (uses SessionPolicyController, costs extra tokens)
    session_policy: str = "none"
    # Knobs for `rule` mode (ignored otherwise).
    policy_max_refusals: int = 3
    policy_suspicion_per_refusal: float = 0.2
    policy_suspicion_decay: float = 0.1
    policy_abandon_suspicion: float = 0.75


@dataclass(frozen=True)
class LLMSpec:
    """Single LLM spec that the factory turns into both an ARE callable
    and an ASE LangChain chat model."""
    provider: str = "mock"
    model: str = ""
    max_tokens: int = 1024
    temperature: float = 0.7
    api_key_env: str | None = None
    # provider-specific
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    azure_api_version: str | None = None
    bedrock_region: str | None = None
    bedrock_endpoint: str | None = None  # For bedrock-openai provider
    ollama_base_url: str | None = None


@dataclass(frozen=True)
class ComponentOverrides:
    planner: LLMSpec | None = None
    generator: LLMSpec | None = None
    judge: LLMSpec | None = None
    policy: LLMSpec | None = None
    user_simulator: LLMSpec | None = None


@dataclass(frozen=True)
class AdversarialScenario:
    scenario_id: str
    scenario_type: str
    scenario_text: str
    hijack_target: str | None = None
    failure_threshold: int = 3
    judge_overrides: dict[str, Any] = field(default_factory=dict)
    # Soft fresh-start: when N consecutive adversarial probes are refused, push the
    # attacker's planner to rotate to a different angle/sub_tactic next turn. Does NOT
    # restart the session or the target chat history. Set to 0 to disable.
    fresh_start_after_refusals: int = 2


@dataclass(frozen=True)
class Schedule:
    """How to choose synth vs adversarial mode for each turn within a conversation.

    Modes:
      - "bernoulli": each turn is an independent coin flip with P(synth) = p_synth.
        Backwards-compatible default.
      - "phased":    first `warmup_turns` are synth, the rest are adversarial.
                     Use for realistic "establish context then attack" patterns.
      - "min_each":  guarantee at least `min_synth` synth and `min_adversarial`
                     adversarial turns, then fill the rest by Bernoulli at p_synth.
      - "ramp":      first `warmup_turns` are synth, then P(adversarial) climbs
                     linearly to 1 across the remaining turns — a gradual hand-off
                     from legitimate context-building to sustained adversarial pressure.
    """
    mode: str = "bernoulli"
    p_synth: float = 0.3  # used by bernoulli and min_each (default leans adversarial)
    warmup_turns: int = 2  # used by phased and ramp
    min_synth: int = 0  # used by min_each
    min_adversarial: int = 0  # used by min_each


@dataclass(frozen=True)
class EvalPlanEntry:
    persona_id: str
    synth_scenario_id: str
    adversarial_scenario_id: str
    weight: float = 1.0
    schedule: Schedule = field(default_factory=Schedule)
    max_turns: int | None = None
    # DEPRECATED — kept for backwards compatibility with older contracts.
    # If set and `schedule` is the default, parser populates Schedule(mode=bernoulli, p_synth=this).
    synth_to_adversarial_ratio: float | None = None


@dataclass(frozen=True)
class EvalPlan:
    # Optional: omit to let the token budget drive how many conversations run.
    # When None, the runner behaves as if run.until_budget_exhausted=True.
    total_conversations: int | None
    conversation_turns: ConversationTurns
    entries: list[EvalPlanEntry]
    attack_memory: str = "shared"  # shared | per_persona | none


@dataclass(frozen=True)
class TrajectoryConfig:
    """Trajectory-aware evaluation toggle, controlled entirely from the contract YAML.

    When `enabled`, adversarial turns also evaluate the target's internal execution
    trajectory (routing, handoffs, tool calls, memory, retrieval) — read inline from
    `trace_field` in the target's JSON response — in addition to the final response.
    When disabled (the default, or when the `trajectory:` block is omitted), behavior
    is identical to today's response-only evaluation.
    """
    enabled: bool = False
    trace_field: str = "trace"


@dataclass(frozen=True)
class ScoringConfig:
    synth_weights: dict[str, float] = field(default_factory=lambda: {
        "groundedness": 1.0, "relevance": 1.0, "safety": 1.0, "clarification": 1.0
    })
    adversarial_failure_threshold: int = 3


@dataclass(frozen=True)
class UnifiedContract:
    suite: Suite
    run: RunSettings
    llm: LLMSpec
    components: ComponentOverrides
    target: TargetChatbot
    time_window: TimeWindow
    persona_pool: list[Persona]
    scenario_catalog: list[Scenario]
    adversarial_scenario_catalog: list[AdversarialScenario]
    eval_plan: EvalPlan
    scoring: ScoringConfig
    output: OutputConfig
    target_llm: LLMSpec | None = None  # Used when target.mode == "llm"
    target_system_prompt: str = ""  # Bot's behavioral prompt when target.mode == "llm"
    trajectory: TrajectoryConfig = field(default_factory=TrajectoryConfig)
    warnings: list[str] = field(default_factory=list)

    def persona_by_id(self) -> dict[str, Persona]:
        return {p.persona_id: p for p in self.persona_pool}

    def scenario_by_id(self) -> dict[str, Scenario]:
        return {s.scenario_id: s for s in self.scenario_catalog}

    def adversarial_by_id(self) -> dict[str, AdversarialScenario]:
        return {a.scenario_id: a for a in self.adversarial_scenario_catalog}

    def llm_for(self, component: str) -> LLMSpec:
        """Return per-component LLMSpec, falling back to top-level llm."""
        override = getattr(self.components, component, None)
        return override or self.llm
