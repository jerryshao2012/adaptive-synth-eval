from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricContentFingerprint:
    """Per-metric fingerprint pair for version tracking.

    content_fingerprint: changes when prompt, thresholds, heuristic, or scoring
        logic changes — triggers LLM re-evaluation for this metric.
    policy_fingerprint: changes only when thresholds change — triggers status
        recalculation without LLM calls.
    """

    content_fingerprint: str
    policy_fingerprint: str


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
    prompt_template: str
    heuristic: dict[str, Any] | None = None
    content_fingerprint: str | None = None
