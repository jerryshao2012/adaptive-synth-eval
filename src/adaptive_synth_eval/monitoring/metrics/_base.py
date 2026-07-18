from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_JUDGE_PROVIDER_ALIASES = {
    "azure": "azure_openai",
    "azureopenai": "azure_openai",
    "azure_openai": "azure_openai",
    "anthropic": "anthropic",
    "openai": "openai",
    "ollama": "ollama",
    "bedrock": "bedrock",
}


@dataclass(frozen=True)
class JudgeSpec:
    """Optional provider/model override for one monitoring metric."""

    provider: str
    model: str | None = None
    api_key_env: str | None = None


def parse_judge_spec(value: Any, *, metric_key: str) -> JudgeSpec | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"Metric '{metric_key}' judge must be a mapping.")

    allowed = {"provider", "model", "api_key_env"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(
            f"Metric '{metric_key}' judge contains unknown field(s): {', '.join(unknown)}"
        )

    provider_value = value.get("provider")
    if not isinstance(provider_value, str) or not provider_value.strip():
        raise ValueError(f"Metric '{metric_key}' judge.provider must be non-empty.")
    normalized = provider_value.strip().lower().replace("-", "_")
    provider = _JUDGE_PROVIDER_ALIASES.get(normalized)
    if provider is None:
        raise ValueError(
            f"Unsupported judge provider '{provider_value}' for metric '{metric_key}'."
        )

    optional: dict[str, str | None] = {}
    for field_name in ("model", "api_key_env"):
        field_value = value.get(field_name)
        if field_value is not None and (
                not isinstance(field_value, str) or not field_value.strip()
        ):
            raise ValueError(
                f"Metric '{metric_key}' judge.{field_name} must be non-empty when provided."
            )
        optional[field_name] = field_value.strip() if isinstance(field_value, str) else None

    return JudgeSpec(provider=provider, **optional)


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
    judge: JudgeSpec | None = None
