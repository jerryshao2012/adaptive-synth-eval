import json
from types import SimpleNamespace

import pytest

from adaptive_synth_eval.clients.llm import LLMClient
from adaptive_synth_eval.monitoring import runner
from adaptive_synth_eval.monitoring.evaluator import (
    EvaluationInput,
    JudgeConfigurationError,
    MetricEvaluator,
    MetricSelectionError,
)
from adaptive_synth_eval.monitoring.metric_definitions import load_metrics_config


class FakeJudge:
    model_provider = "openai"
    config = {"model": "test-judge"}

    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append((json.loads(prompt), kwargs))
        content, error = next(self._responses)
        return SimpleNamespace(content=content, error=error)


def test_evaluator_preserves_selected_metric_order_and_audit_fields():
    judge = FakeJudge(
        [
            ('{"relevance": 0.75}', None),
            ('{"toxicity": 0.2}', None),
        ]
    )
    evaluator = MetricEvaluator(
        metrics_config=load_metrics_config(),
        default_llm=judge,
    )

    result = evaluator.evaluate(
        EvaluationInput(
            user_message="What is the leave policy?",
            chatbot_response="Employees receive twenty days.",
        ),
        metric_keys=["relevance", "toxicity"],
    )

    assert [metric.metric_key for metric in result.results] == [
        "relevance",
        "toxicity",
    ]
    assert result.results[0].score == 0.75
    assert result.results[0].percent == 75.0
    assert result.results[0].status == "warn"
    assert result.results[0].quality == "llm"
    assert result.results[0].reference_mode == "not_applicable"
    assert result.results[1].score == 0.8
    assert result.results[1].quality == "llm"
    assert len(result.results[0].content_fingerprint) == 16
    assert len(result.results[0].policy_fingerprint) == 16
    assert len(result.results[0].judge_fingerprint) == 16
    assert len(judge.calls) == 2


def test_monitoring_row_projection_uses_public_metric_evaluator(monkeypatch):
    calls = []
    original = MetricEvaluator.evaluate

    def tracked_evaluate(self, inputs, **kwargs):
        calls.append(inputs)
        return original(self, inputs, **kwargs)

    monkeypatch.setattr(MetricEvaluator, "evaluate", tracked_evaluate)
    config = load_metrics_config()
    llm = LLMClient(enabled=False)
    batches = runner._build_judge_batches(
        config,
        default_llm=llm,
        dry_run=True,
    )

    row = runner._evaluate_chat_row(
        chat_row={
            "conversation_id": "conversation-1",
            "turn_id": "turn-1",
            "user_message": "Question",
            "bot_response": "Answer",
        },
        dry_run=True,
        metrics_config=config,
        judge_batches=batches,
        evaluation_fingerprint="evaluation-fp",
        policy_fingerprints={key: "policy-fp" for key in config.metrics},
        sample_window_id=1,
        source_line_index=0,
        started_at="2026-07-21T00:00:00-04:00",
    )

    assert row["safety_metrics"]["toxicity"]["score"] == 1.0
    assert calls == [
        EvaluationInput(
            user_message="Question",
            chatbot_response="Answer",
        )
    ]


@pytest.mark.parametrize(
    ("metric_keys", "code"),
    [
        ([], "invalid_metric_selection"),
        (["relevance", "relevance"], "invalid_metric_selection"),
        (["missing"], "unknown_metric"),
    ],
)
def test_evaluator_rejects_invalid_metric_selections(metric_keys, code):
    evaluator = MetricEvaluator(
        metrics_config=load_metrics_config(),
        default_llm=FakeJudge([]),
    )

    with pytest.raises(MetricSelectionError) as exc_info:
        evaluator.evaluate(
            EvaluationInput(user_message="Question", chatbot_response="Answer"),
            metric_keys=metric_keys,
        )

    assert exc_info.value.code == code


def test_evaluator_isolates_runtime_fallback_to_affected_batch():
    judge = FakeJudge(
        [
            ("", "provider unavailable"),
            ('{"toxicity": 0.2}', None),
        ]
    )
    evaluator = MetricEvaluator(
        metrics_config=load_metrics_config(),
        default_llm=judge,
    )

    result = evaluator.evaluate(
        EvaluationInput(user_message="Question", chatbot_response="Answer"),
        metric_keys=["relevance", "toxicity"],
    )

    assert result.results[0].quality == "heuristic_fallback"
    assert result.results[1].quality == "llm"
    assert result.results[1].score == 0.8


def test_evaluator_reports_reference_modes_and_sends_reference_payloads():
    judge = FakeJudge(
        [
            ('{"groundedness": 0.8, "completeness": 0.6}', None),
        ]
    )
    evaluator = MetricEvaluator(
        metrics_config=load_metrics_config(),
        default_llm=judge,
    )

    result = evaluator.evaluate(
        EvaluationInput(
            user_message="Question",
            chatbot_response="Answer",
            reference_context="Context",
        ),
        metric_keys=["groundedness", "completeness"],
    )

    assert [metric.reference_mode for metric in result.results] == [
        "reference_backed",
        "query_only",
    ]
    assert judge.calls[0][0] == {
        "user_message": "Question",
        "chatbot_response": "Answer",
        "reference_context": "Context",
    }


def test_evaluator_startup_rejects_missing_provider(monkeypatch):
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OLLAMA_BASE_URL",
        "OLLAMA_API_BASE",
        "AWS_BEARER_TOKEN_BEDROCK",
    ):
        monkeypatch.delenv(name, raising=False)
    evaluator = MetricEvaluator(metrics_config=load_metrics_config())

    with pytest.raises(JudgeConfigurationError, match="No LLM provider"):
        evaluator.validate_startup(initialize_models=False)


def test_evaluator_provider_auto_detection_keeps_monitoring_precedence(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://azure.example")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "azure-judge")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    evaluator = MetricEvaluator(metrics_config=load_metrics_config())
    evaluator.validate_startup(initialize_models=False)

    assert evaluator.default_llm.model_provider == "azure_openai"


def test_metric_evaluator_is_part_of_monitoring_public_api():
    from adaptive_synth_eval.monitoring import MetricEvaluator as PublicEvaluator

    assert PublicEvaluator is MetricEvaluator
