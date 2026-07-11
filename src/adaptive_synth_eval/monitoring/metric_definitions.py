"""Metric definitions loaded from metrics.yaml.

Provides the single source of truth for all monitoring metric configuration:
metric keys, evaluation groups, thresholds, descriptions, and the LLM prompt template.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MetricDefinition:
    """Immutable definition of a single evaluation metric."""

    key: str
    evaluation_group: str
    label: str
    description: str
    detail: str
    eval_input_key: str
    warn_below: float
    fail_below: float
    invert_llm_score: bool


@dataclass(frozen=True)
class MetricsConfig:
    """Complete monitoring metrics configuration loaded from YAML."""

    metrics: dict[str, MetricDefinition]
    prompt_template: str
    evaluation_groups: frozenset[str]
    metric_keys_by_group: dict[str, list[str]]


# Module-level cache: parsed once per process, never reloaded.
_CACHED_CONFIG: MetricsConfig | None = None

_DEFAULT_PATH = Path(__file__).resolve().parent / "metrics.yaml"


def load_metrics_config(path: Path | None = None) -> MetricsConfig:
    """Load and validate the metrics configuration from YAML.

    Args:
        path: Optional override path to metrics.yaml (primarily for tests).
              Defaults to the metrics.yaml shipped alongside this module.

    Returns:
        A frozen MetricsConfig with all metric definitions and evaluation settings.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        ValueError: If the YAML is malformed or missing required fields.
    """
    global _CACHED_CONFIG

    if path is None and _CACHED_CONFIG is not None:
        return _CACHED_CONFIG

    resolved = Path(path) if path is not None else _DEFAULT_PATH

    if not resolved.exists():
        raise FileNotFoundError(f"Metrics configuration not found at: {resolved}")

    with resolved.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError("metrics.yaml must contain a top-level mapping.")

    metrics_raw = raw.get("metrics")
    if not isinstance(metrics_raw, dict) or not metrics_raw:
        raise ValueError("metrics.yaml must define a non-empty 'metrics' mapping.")

    llm_raw = raw.get("llm_evaluation")
    if not isinstance(llm_raw, dict):
        raise ValueError("metrics.yaml must define an 'llm_evaluation' section.")

    prompt_template = llm_raw.get("prompt_template")
    if not isinstance(prompt_template, str) or not prompt_template.strip():
        raise ValueError("llm_evaluation.prompt_template must be a non-empty string.")

    metrics: dict[str, MetricDefinition] = {}
    groups: set[str] = set()
    keys_by_group: dict[str, list[str]] = {}

    for key, defn in metrics_raw.items():
        if not isinstance(defn, dict):
            raise ValueError(f"Metric '{key}' must be a mapping, got {type(defn).__name__}.")

        evaluation_group = _require_str(defn, key, "evaluation_group")
        label = _require_str(defn, key, "label")
        description = _require_str(defn, key, "description")
        detail = _require_str(defn, key, "detail")
        eval_input_key = _require_str(defn, key, "eval_input_key")

        thresholds = defn.get("thresholds")
        if not isinstance(thresholds, dict):
            raise ValueError(f"Metric '{key}' must have a 'thresholds' mapping.")

        warn_below = _require_float(thresholds, key, "warn_below")
        fail_below = _require_float(thresholds, key, "fail_below")

        if fail_below >= warn_below:
            raise ValueError(
                f"Metric '{key}': fail_below ({fail_below}) must be less than "
                f"warn_below ({warn_below})."
            )

        invert = bool(defn.get("invert_llm_score", False))

        metric = MetricDefinition(
            key=key,
            evaluation_group=evaluation_group,
            label=label,
            description=description,
            detail=detail,
            eval_input_key=eval_input_key,
            warn_below=warn_below,
            fail_below=fail_below,
            invert_llm_score=invert,
        )
        metrics[key] = metric
        groups.add(evaluation_group)
        keys_by_group.setdefault(evaluation_group, []).append(key)

    if not metrics:
        raise ValueError("metrics.yaml must define at least one metric.")

    config = MetricsConfig(
        metrics=metrics,
        prompt_template=prompt_template.strip(),
        evaluation_groups=frozenset(groups),
        metric_keys_by_group=keys_by_group,
    )

    if path is None:
        _CACHED_CONFIG = config

    return config


def _require_str(mapping: dict[str, Any], metric_key: str, field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Metric '{metric_key}' must have a non-empty '{field}' string.")
    return value.strip()


def _require_float(mapping: dict[str, Any], metric_key: str, field: str) -> float:
    value = mapping.get(field)
    if value is None:
        raise ValueError(f"Metric '{metric_key}' thresholds must include '{field}'.")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"Metric '{metric_key}' thresholds.{field} must be numeric, got {value!r}."
        ) from None
