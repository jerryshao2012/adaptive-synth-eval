"""Fingerprint computation for evaluation and policy versioning.

Generates stable SHA-256 hex digests from canonicalized JSON inputs.
Fingerprints are truncated to 16 hex characters (64 bits) — sufficient for
uniqueness at the scale of metric configurations (collision probability
~2.7e-14 at 1,000 fingerprints).
"""

from __future__ import annotations

import hashlib
import json

from adaptive_synth_eval.clients.llm import LLMClient


def compute_evaluation_fingerprint(
        *,
        prompt_template: str,
        model_provider: str,
        model_identifier: str,
        metric_keys: list[str],
        metric_details: list[str],
) -> str:
    """Compute a stable evaluation fingerprint from the effective evaluation inputs.

    The fingerprint captures everything that affects the LLM evaluation output:
    prompt text, model identity, and which metrics are being scored.

    Changing any of these inputs produces a different fingerprint, which signals
    that a fresh LLM evaluation is required.

    Args:
        prompt_template: The full prompt template sent to the LLM.
        model_provider: Normalized provider string (e.g. "azure_openai").
        model_identifier: Deployment name or model name used for evaluation.
        metric_keys: Ordered list of metric keys being evaluated.
        metric_details: Ordered list of metric description strings.

    Returns:
        16-character hex digest of the SHA-256 hash.
    """
    payload = {
        "prompt_template": prompt_template,
        "model_provider": model_provider,
        "model_identifier": model_identifier,
        "metric_keys": sorted(metric_keys),
        "metric_details": sorted(metric_details),
    }
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
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
        return deployment or "azure_openai"

    if provider in ("anthropic", "openai", "ollama", "bedrock"):
        import os
        model = os.getenv("MODEL_NAME", "").strip()
        return model or provider

    return provider
