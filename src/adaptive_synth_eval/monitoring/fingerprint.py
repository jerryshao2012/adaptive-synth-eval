"""Fingerprint computation for evaluation and policy versioning.

Generates stable SHA-256 hex digests from canonicalized JSON inputs.
Fingerprints are truncated to 16 hex characters (64 bits) — sufficient for
uniqueness at the scale of metric configurations (collision probability
~2.7e-14 at 1,000 fingerprints).

Three fingerprint tiers:
1. **metric content** — per-metric: prompt, thresholds, heuristic, scoring logic.
   Changing content triggers LLM re-evaluation for that metric's group.
2. **policy** — per-metric: thresholds only. Changing thresholds triggers status
   recalculation only — no LLM calls.
3. **evaluation (composite)** — the union of all per-metric content fingerprints
   + model identity. Changing any metric content or switching models produces
   a new composite fingerprint, signalling that a fresh LLM evaluation is needed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from adaptive_synth_eval.clients.llm import LLMClient


def compute_metric_content_fingerprint(
        *,
        metric_key: str,
        prompt_template: str,
        eval_input_key: str,
        invert_llm_score: bool,
        heuristic: dict[str, Any] | None,
) -> str:
    """Compute a stable content fingerprint for a single metric.

    Covers everything that affects the evaluator's score for this metric: the
    canonicalized prompt text, scoring inversion flag, output key, and
    heuristic fallback rules. Thresholds are deliberately excluded because
    they classify an existing score rather than change its value.

    Changing any of these produces a different fingerprint, signalling that this
    metric needs LLM re-evaluation.

    Args:
        metric_key: The metric key (e.g. "toxicity").
        prompt_template: The per-metric prompt template sent to the LLM.
        eval_input_key: The JSON key the LLM returns for this metric.
        invert_llm_score: Whether the LLM score is inverted (1.0 - raw).
        heuristic: Optional heuristic fallback configuration dict.

    Returns:
        16-character hex digest of the SHA-256 hash.
    """
    # Canonicalize heuristic: sort keys, convert lists to tuples for stable hashing.
    canonical_heuristic: Any = None
    if isinstance(heuristic, dict):
        canonical_heuristic = _canonicalize(heuristic)

    payload: dict[str, Any] = {
        "metric_key": metric_key,
        "prompt_template": canonicalize_prompt_template(prompt_template),
        "eval_input_key": eval_input_key,
        "invert_llm_score": invert_llm_score,
        "heuristic": canonical_heuristic,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def canonicalize_prompt_template(prompt_template: str) -> str:
    """Normalize source-formatting differences without changing prompt meaning."""
    lines = prompt_template.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    nonblank = [line for line in lines if line]
    indent = min(
        (len(line) - len(line.lstrip(" \t")) for line in nonblank),
        default=0,
    )
    return "\n".join(line[indent:] if line else "" for line in lines)


def compute_evaluation_fingerprint(
        *,
        metric_content_fingerprints: dict[str, str],
        model_provider: str,
        model_identifier: str,
        judge_protocol_version: str | None = None,
        judge_settings: dict[str, Any] | None = None,
        metric_judge_fingerprints: dict[str, str] | None = None,
) -> str:
    """Compute a composite fingerprint from metric, model, and judge configuration.

    The fingerprint captures everything that affects LLM evaluation outputs:
    every metric's prompt/template/thresholds/heuristic, model identity, and
    optional metric-routed judge protocol/settings.

    Changing any metric's content OR switching model/ deployment produces a
    different fingerprint, which signals that a fresh LLM evaluation is required.

    Args:
        metric_content_fingerprints: Mapping of metric_key → content_fingerprint.
        model_provider: Normalized provider string (e.g. "azure_openai").
        model_identifier: Deployment name or model name used for evaluation.

    Returns:
        16-character hex digest of the SHA-256 hash.
    """
    payload: dict[str, Any] = {
        "metric_content_fingerprints": dict(sorted(metric_content_fingerprints.items())),
        "model_provider": model_provider,
        "model_identifier": model_identifier,
    }
    if judge_protocol_version is not None:
        payload["judge_protocol_version"] = judge_protocol_version
    if judge_settings is not None:
        payload["judge_settings"] = judge_settings
    if metric_judge_fingerprints is not None:
        payload["metric_judge_fingerprints"] = dict(
            sorted(metric_judge_fingerprints.items())
        )
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compute_policy_fingerprint(
        *,
        metric_key: str,
        warn_below: float,
        fail_below: float,
) -> str:
    """Compute a stable policy fingerprint for a single metric's thresholds.

    Changing thresholds does not invalidate existing LLM scores — only the
    pass/warn/fail status labels need recalculation. The policy fingerprint
    detects threshold-only changes so they can be handled without LLM calls.

    Args:
        metric_key: The metric key (e.g. "relevance").
        warn_below: Score percentage below which status becomes "warn".
        fail_below: Score percentage below which status becomes "fail".

    Returns:
        16-character hex digest of the SHA-256 hash.
    """
    payload = {
        "metric_key": metric_key,
        "warn_below": warn_below,
        "fail_below": fail_below,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def resolve_model_identifier(llm: LLMClient) -> str:
    """Resolve a human-readable model identifier from the LLM client configuration.

    The identifier is used in fingerprint computation to detect model/deployment
    changes that would affect evaluation scores.

    Args:
        llm: A configured (or unconfigured) LLMClient instance.

    Returns:
        A string like "eval-judge" (Azure deployment), "claude-sonnet-4-5" (Anthropic),
        or "dry_run" / "none" when no real LLM is configured.
    """
    provider = llm.model_provider or "none"

    if provider == "azure_openai":
        import os

        configured = str(
            llm.config.get("azure_deployment")
            or llm.config.get("model")
            or ""
        ).strip()
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
        return configured or deployment or "azure_openai"

    if provider in ("anthropic", "openai", "ollama", "bedrock"):
        import os

        configured = str(llm.config.get("model") or "").strip()
        model = os.getenv("MODEL_NAME", "").strip()
        return configured or model or provider

    return provider


def _canonicalize(value: Any) -> Any:
    """Recursively canonicalize a value for stable JSON serialization.

    Converts lists to tuples (hashable, ordered) and dicts to sorted key-value
    pairs so that equivalent structures produce identical JSON output.
    """
    if isinstance(value, dict):
        return tuple(sorted((k, _canonicalize(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_canonicalize(item) for item in value)
    return value
