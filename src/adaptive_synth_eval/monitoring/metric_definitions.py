"""Metric definitions loaded from metrics/*.yaml.

Provides the single source of truth for all monitoring metric configuration:
metric keys, evaluation groups, thresholds, descriptions, per-metric content
fingerprints, and policy fingerprints.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from adaptive_synth_eval.monitoring.fingerprint import compute_metric_content_fingerprint
from .metrics._base import MetricSpec as MetricDefinition
from .metrics.registry import MetricRegistry


@dataclass(frozen=True)
class MetricsConfig:
    """Complete monitoring metrics configuration loaded from YAML."""

    metrics: dict[str, MetricDefinition]
    metric_content_fingerprints: dict[str, str]
    evaluation_groups: frozenset[str]
    metric_keys_by_group: dict[str, list[str]]


# Module-level cache: parsed once per process, never reloaded.
_CACHED_CONFIG: MetricsConfig | None = None


def load_metrics_config(path: Path | None = None) -> MetricsConfig:
    """Load and validate the metrics configuration.

    Args:
        path: Optional override path to a custom metrics.yaml file.

    Returns:
        A frozen MetricsConfig with all metric definitions and evaluation settings.
    """
    global _CACHED_CONFIG

    if path is None and _CACHED_CONFIG is not None:
        return _CACHED_CONFIG

    # Support loading from a custom path if explicitly provided
    # (for backward compatibility / tests).
    if path is not None:
        resolved = Path(path)
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

            _validate_thresholds(key, warn_below, fail_below)

            invert = bool(defn.get("invert_llm_score", False))

            h_data = defn.get("heuristic")
            h_rule: dict | None = h_data if isinstance(h_data, dict) else None

            content_fp = compute_metric_content_fingerprint(
                metric_key=key,
                prompt_template=prompt_template,
                eval_input_key=eval_input_key,
                invert_llm_score=invert,
                heuristic=h_rule,
            )

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
                prompt_template=prompt_template,
                heuristic=h_rule,
                content_fingerprint=content_fp,
            )
            metrics[key] = metric
            groups.add(evaluation_group)
            keys_by_group.setdefault(evaluation_group, []).append(key)

        content_fingerprints = {k: m.content_fingerprint for k, m in metrics.items() if m.content_fingerprint}

        return MetricsConfig(
            metrics=metrics,
            metric_content_fingerprints=content_fingerprints,
            evaluation_groups=frozenset(groups),
            metric_keys_by_group=keys_by_group,
        )

    # Discover and load from the default registry.
    registry = MetricRegistry()
    specs = registry.all_specs()

    metrics: dict[str, MetricDefinition] = {k: v for k, v in specs.items()}
    groups = frozenset(spec.evaluation_group for spec in specs.values())

    keys_by_group: dict[str, list[str]] = {}
    for spec in specs.values():
        keys_by_group.setdefault(spec.evaluation_group, []).append(spec.key)

    content_fingerprints = {
        k: v.content_fingerprint
        for k, v in specs.items()
        if v.content_fingerprint is not None
    }

    config = MetricsConfig(
        metrics=metrics,
        metric_content_fingerprints=content_fingerprints,
        evaluation_groups=groups,
        metric_keys_by_group=keys_by_group,
    )

    _CACHED_CONFIG = config
    return config


def _validate_thresholds(key: str, warn_below: float, fail_below: float) -> None:
    if fail_below >= warn_below:
        raise ValueError(
            f"Metric '{key}': fail_below ({fail_below}) must be less than "
            f"warn_below ({warn_below})."
        )


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
