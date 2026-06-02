# engine/config.py
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyConfig:
    max_refusals: int = 3
    suspicion_per_refusal: float = 0.2
    suspicion_decay: float = 0.1  # NEW: applied on a non-refusal turn
    abandon_suspicion: float = 0.75
    planner_backoff_suspicion: float = 0.5
    planner_switch_refusals: int = 2


@dataclass(frozen=True)
class RunConfig:
    max_turns: int = 8
    failure_threshold: int = 3
    seed: int | None = None  # NEW: determinism
    temperature: float = 0.7  # NEW
    policy: PolicyConfig = PolicyConfig()
