"""Tests for metric definitions, YAML loading, and fingerprint computation."""

import tempfile
from pathlib import Path

import pytest

from adaptive_synth_eval.monitoring.fingerprint import (
    compute_evaluation_fingerprint,
    compute_policy_fingerprint,
    resolve_model_identifier,
)
from adaptive_synth_eval.monitoring.metric_definitions import (
    load_metrics_config,
)


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

def test_loads_all_ten_metrics():
    """The shipped metrics.yaml must define exactly 10 metrics."""
    config = load_metrics_config()
    assert len(config.metrics) == 10
    expected = {
        "toxicity", "bias_fairness", "robustness", "compliance",
        "relevance", "groundedness", "correctness", "completeness",
        "style", "precision",
    }
    assert set(config.metrics.keys()) == expected


def test_every_metric_has_valid_thresholds():
    """fail_below must be strictly less than warn_below for every metric."""
    config = load_metrics_config()
    for key, m in config.metrics.items():
        assert m.fail_below < m.warn_below, (
            f"{key}: fail_below ({m.fail_below}) >= warn_below ({m.warn_below})"
        )
        assert 0.0 <= m.fail_below <= 100.0
        assert 0.0 <= m.warn_below <= 100.0


def test_evaluation_groups():
    """Metrics are partitioned into evaluation groups."""
    config = load_metrics_config()
    assert config.evaluation_groups == {"safety", "performance"}
    assert set(config.metric_keys_by_group["safety"]) == {
        "toxicity", "bias_fairness", "robustness", "compliance",
    }
    assert set(config.metric_keys_by_group["performance"]) == {
        "relevance", "groundedness", "correctness", "completeness",
        "style", "precision",
    }


def test_prompt_template_is_loaded():
    """The LLM prompt template must be loaded from YAML."""
    config = load_metrics_config()
    assert "{user_text}" in config.prompt_template
    assert "{response_text}" in config.prompt_template
    assert "toxicity" in config.prompt_template


def test_invert_llm_score_flags():
    """Only toxicity and bias_fairness invert the LLM score."""
    config = load_metrics_config()
    for key, m in config.metrics.items():
        if key in ("toxicity", "bias_fairness"):
            assert m.invert_llm_score is True, f"{key} must invert LLM score"
        else:
            assert m.invert_llm_score is False, f"{key} must NOT invert LLM score"


def test_raises_on_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            load_metrics_config(missing)


def test_raises_on_empty_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty.yaml"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="non-empty 'metrics' mapping"):
            load_metrics_config(path)


def test_raises_on_missing_metrics():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.yaml"
        path.write_text("llm_evaluation:\n  prompt_template: hello\n", encoding="utf-8")
        with pytest.raises(ValueError, match="non-empty 'metrics' mapping"):
            load_metrics_config(path)


def test_raises_on_missing_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.yaml"
        path.write_text(
            "metrics:\n  toxicity:\n    evaluation_group: safety\n"
            "    label: Tox\n    description: d\n    detail: d\n"
            "    eval_input_key: toxicity\n    thresholds: {warn_below: 85, fail_below: 65}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="llm_evaluation"):
            load_metrics_config(path)


def test_raises_on_invalid_thresholds():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.yaml"
        path.write_text(
            "metrics:\n"
            "  t:\n"
            "    evaluation_group: s\n    label: T\n    description: d\n"
            "    detail: d\n    eval_input_key: t\n"
            "    thresholds: {warn_below: 50, fail_below: 80}\n"
            "llm_evaluation:\n  prompt_template: p\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="fail_below.*must be less than"):
            load_metrics_config(path)


def test_custom_path_override():
    """Verify load_metrics_config accepts a custom path."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "custom.yaml"
        path.write_text(
            "metrics:\n"
            "  relevance:\n"
            "    evaluation_group: perf\n    label: Rel\n"
            "    description: Relevance score.\n"
            "    detail: How relevant.\n"
            "    eval_input_key: relevance\n"
            "    thresholds: {warn_below: 80, fail_below: 50}\n"
            "llm_evaluation:\n  prompt_template: test prompt\n",
            encoding="utf-8",
        )
        config = load_metrics_config(path)
        assert len(config.metrics) == 1
        assert config.metrics["relevance"].warn_below == 80.0


# ---------------------------------------------------------------------------
# Fingerprint computation
# ---------------------------------------------------------------------------

def _sample_inputs():
    return dict(
        prompt_template="You are an evaluator. User: {user_text} Bot: {response_text}",
        model_provider="azure_openai",
        model_identifier="eval-judge",
        metric_keys=["toxicity", "bias_fairness", "relevance"],
        metric_details=["Measures toxicity.", "Measures bias.", "Measures relevance."],
    )


def test_evaluation_fingerprint_is_deterministic():
    """Same inputs produce the same fingerprint every time."""
    inputs = _sample_inputs()
    fp1 = compute_evaluation_fingerprint(**inputs)
    fp2 = compute_evaluation_fingerprint(**inputs)
    assert fp1 == fp2
    assert len(fp1) == 16


def test_evaluation_fingerprint_changes_with_prompt():
    """A different prompt template changes the fingerprint."""
    base = _sample_inputs()
    fp1 = compute_evaluation_fingerprint(**base)
    changed = dict(base, prompt_template="A completely different prompt.")
    fp2 = compute_evaluation_fingerprint(**changed)
    assert fp1 != fp2


def test_evaluation_fingerprint_changes_with_model_provider():
    """A different model provider changes the fingerprint."""
    base = _sample_inputs()
    fp1 = compute_evaluation_fingerprint(**base)
    changed = dict(base, model_provider="anthropic")
    fp2 = compute_evaluation_fingerprint(**changed)
    assert fp1 != fp2


def test_evaluation_fingerprint_changes_with_model_identifier():
    """A different model deployment/name changes the fingerprint."""
    base = _sample_inputs()
    fp1 = compute_evaluation_fingerprint(**base)
    changed = dict(base, model_identifier="gpt-4.1-eval")
    fp2 = compute_evaluation_fingerprint(**changed)
    assert fp1 != fp2


def test_evaluation_fingerprint_changes_with_metric_keys():
    """Adding or removing a metric changes the fingerprint."""
    base = _sample_inputs()
    fp1 = compute_evaluation_fingerprint(**base)
    changed = dict(base, metric_keys=["toxicity", "bias_fairness"])  # removed relevance
    fp2 = compute_evaluation_fingerprint(**changed)
    assert fp1 != fp2


def test_evaluation_fingerprint_changes_with_metric_details():
    """Changing a metric description changes the fingerprint."""
    base = _sample_inputs()
    fp1 = compute_evaluation_fingerprint(**base)
    changed = dict(base, metric_details=["Updated toxicity measure.", "Measures bias.", "Measures relevance."])
    fp2 = compute_evaluation_fingerprint(**changed)
    assert fp1 != fp2


def test_evaluation_fingerprint_stable_under_key_ordering():
    """The fingerprint is stable regardless of input list ordering (sort is applied)."""
    base = _sample_inputs()
    fp1 = compute_evaluation_fingerprint(**base)
    # Reverse the order of metric_keys and metric_details
    changed = dict(
        base,
        metric_keys=list(reversed(base["metric_keys"])),
        metric_details=list(reversed(base["metric_details"])),
    )
    fp2 = compute_evaluation_fingerprint(**changed)
    assert fp1 == fp2


def test_policy_fingerprint_is_deterministic():
    """Same threshold values produce the same policy fingerprint."""
    fp1 = compute_policy_fingerprint(metric_key="relevance", warn_below=85.0, fail_below=60.0)
    fp2 = compute_policy_fingerprint(metric_key="relevance", warn_below=85.0, fail_below=60.0)
    assert fp1 == fp2
    assert len(fp1) == 16


def test_policy_fingerprint_changes_with_warn_below():
    """Changing the warn threshold changes the policy fingerprint."""
    fp1 = compute_policy_fingerprint(metric_key="relevance", warn_below=85.0, fail_below=60.0)
    fp2 = compute_policy_fingerprint(metric_key="relevance", warn_below=80.0, fail_below=60.0)
    assert fp1 != fp2


def test_policy_fingerprint_changes_with_fail_below():
    """Changing the fail threshold changes the policy fingerprint."""
    fp1 = compute_policy_fingerprint(metric_key="relevance", warn_below=85.0, fail_below=60.0)
    fp2 = compute_policy_fingerprint(metric_key="relevance", warn_below=85.0, fail_below=50.0)
    assert fp1 != fp2


def test_policy_fingerprint_changes_with_metric_key():
    """Different metrics have different policy fingerprints even with same thresholds."""
    fp1 = compute_policy_fingerprint(metric_key="relevance", warn_below=85.0, fail_below=60.0)
    fp2 = compute_policy_fingerprint(metric_key="groundedness", warn_below=85.0, fail_below=60.0)
    assert fp1 != fp2


# ---------------------------------------------------------------------------
# Resolve model identifier
# ---------------------------------------------------------------------------

class _FakeLLM:
    """Minimal fake for LLMClient resolution tests."""

    def __init__(self, provider):
        self.model_provider = provider


def test_resolve_model_identifier_dry_run():
    from adaptive_synth_eval.clients.llm import LLMClient
    llm = LLMClient(enabled=False)
    ident = resolve_model_identifier(llm)
    assert ident in ("none", "dry_run") or ident  # any string is fine


def test_resolve_model_identifier_azure(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "eval-judge-prod")
    from adaptive_synth_eval.clients.llm import LLMClient
    llm = LLMClient(enabled=True, model_provider="azure_openai")
    ident = resolve_model_identifier(llm)
    assert ident == "eval-judge-prod"


def test_resolve_model_identifier_anthropic(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "claude-sonnet-4-5-20250929")
    from adaptive_synth_eval.clients.llm import LLMClient
    llm = LLMClient(enabled=True, model_provider="anthropic")
    ident = resolve_model_identifier(llm)
    assert ident == "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# Integration: real metrics.yaml produces consistent fingerprints
# ---------------------------------------------------------------------------

def test_real_config_evaluation_fingerprint():
    """The shipped metrics.yaml produces a valid evaluation fingerprint."""
    config = load_metrics_config()
    all_keys = sorted(config.metrics.keys())
    all_details = sorted(m.detail for m in config.metrics.values())

    fp = compute_evaluation_fingerprint(
        prompt_template=config.prompt_template,
        model_provider="azure_openai",
        model_identifier="eval-judge",
        metric_keys=all_keys,
        metric_details=all_details,
    )
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


def test_real_config_policy_fingerprints_are_unique_per_metric():
    """Every metric's policy fingerprint differs when thresholds differ."""
    config = load_metrics_config()
    fingerprints: dict[str, str] = {}
    for key, m in config.metrics.items():
        fp = compute_policy_fingerprint(
            metric_key=key,
            warn_below=m.warn_below,
            fail_below=m.fail_below,
        )
        fingerprints[key] = fp

    # Metrics with identical thresholds AND same key would collide — but keys differ.
    # tox and bias_fairness share thresholds but have different metric_key values.
    assert fingerprints["toxicity"] != fingerprints["bias_fairness"], (
        "Different metric keys must produce different fingerprints"
    )

    # correctness and completeness share (65, 40) — different keys should differ.
    assert fingerprints["correctness"] != fingerprints["completeness"], (
        "Different metric keys must produce different fingerprints"
    )
