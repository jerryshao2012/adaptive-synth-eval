from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HeuristicRule:
    """Heuristic scoring rule for fallback or dry-runs."""

    default_score: float
    keyword_penalties: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class MetricSpec:
    """Immutable definition of a single evaluation metric, prompt, and heuristics."""

    key: str
    evaluation_group: str
    label: str
    description: str
    detail: str
    eval_input_key: str
    warn_below: float
    fail_below: float
    invert_llm_score: bool
    version: str
    prompt_template: str
    heuristic: HeuristicRule | None = None
