"""Per-component token + USD bookkeeping.

Wraps the existing TokenBudgetManager (which only tracks attacker-side ARE calls)
with per-component breakdowns AND tracks synth / target calls separately so the
budget reflects the full run cost.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from adaptive_synth_eval.adversarial_response_engine.core.token_budget import TokenBudgetManager, TokenUsage

# USD per 1M tokens. Keep this small and explicit; users can override via contract
# if their pricing is different. (Numbers as of 2026-06; double-check against the
# provider's current pricing before publishing cost claims externally.)
_DEFAULT_PRICING_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    # Anthropic Claude
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-7": {"input": 15.00, "output": 75.00},
    # Amazon Nova
    "nova-micro-v1:0": {"input": 0.20, "output": 0.40},
    # Mock = free
    "mock": {"input": 0.0, "output": 0.0},
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Best-effort USD estimate. Unknown models return 0.0 with no error."""
    rates = None
    for key, val in _DEFAULT_PRICING_PER_1M_TOKENS.items():
        if key in model:
            rates = val
            break
    if rates is None:
        return 0.0
    return (
            prompt_tokens * rates["input"] / 1_000_000
            + completion_tokens * rates["output"] / 1_000_000
    )


@dataclass
class ComponentMeter:
    component: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += int(prompt or 0)
        self.completion_tokens += int(completion or 0)
        self.calls += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        return estimate_cost_usd(self.model, self.prompt_tokens, self.completion_tokens)

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "model": self.model,
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass
class BudgetMeter:
    """Aggregates per-component meters and an authoritative TokenBudgetManager.

    The TokenBudgetManager is the source of truth for "are we out of budget?";
    component meters are bookkeeping that also includes synth/target calls that
    used to be invisible.
    """
    budget: TokenBudgetManager
    components: dict[str, ComponentMeter] = field(default_factory=dict)
    _lock: threading.RLock = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._lock = self.budget._lock

    def register(self, component: str, model: str) -> None:
        with self._lock:
            self.components.setdefault(component, ComponentMeter(component=component, model=model))

    def record(self, component: str, prompt: int, completion: int) -> None:
        """Record usage AND charge against the global budget.
        Use for synth and target calls (which don't otherwise hit TokenBudgetManager).
        """
        with self._lock:
            meter = self.components.get(component)
            if meter is None:
                meter = ComponentMeter(component=component, model="unknown")
                self.components[component] = meter
            meter.add(prompt, completion)
            self.budget.add(TokenUsage(
                prompt_tokens=int(prompt or 0), completion_tokens=int(completion or 0)
            ))

    def record_passthrough(self, component: str, prompt: int, completion: int) -> None:
        """Record usage on the per-component meter only; the global budget is
        already being updated elsewhere (e.g. by ARE's LLMClient.complete_json).
        """
        with self._lock:
            meter = self.components.get(component)
            if meter is None:
                meter = ComponentMeter(component=component, model="unknown")
                self.components[component] = meter
            meter.add(prompt, completion)

    @property
    def total_cost_usd(self) -> float:
        with self._lock:
            return sum(m.cost_usd for m in self.components.values())

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "budget": self.budget.snapshot(),
                "components": [meter.to_dict() for meter in self.components.values()],
            }

    @classmethod
    def from_snapshot(cls, payload: dict, *, max_total_tokens: int) -> "BudgetMeter":
        budget = TokenBudgetManager(max_total_tokens=max_total_tokens)
        budget.restore_usage(payload.get("budget", {}))
        meter = cls(budget=budget)
        for raw in payload.get("components", []):
            component = ComponentMeter(
                component=str(raw.get("component", "unknown")),
                model=str(raw.get("model", "unknown")),
                prompt_tokens=int(raw.get("prompt_tokens", 0) or 0),
                completion_tokens=int(raw.get("completion_tokens", 0) or 0),
                calls=int(raw.get("calls", 0) or 0),
            )
            meter.components[component.component] = component
        return meter

    def summary(self, *, stopped_due_to_budget: bool) -> dict:
        with self._lock:
            return {
                "max_total_tokens": self.budget.max_total_tokens,
                "used_total_tokens": self.budget.used_total_tokens,
                "used_prompt_tokens": self.budget.used_prompt_tokens,
                "used_completion_tokens": self.budget.used_completion_tokens,
                "remaining_tokens": self.budget.remaining_tokens,
                "stopped_due_to_budget": stopped_due_to_budget,
                "estimated_cost_usd": round(self.total_cost_usd, 4),
                "per_component": [m.to_dict() for m in self.components.values()],
            }
