"""Unit tests for selective monitoring-score refresh behavior."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from adaptive_synth_eval.clients.llm import LLMClient
from adaptive_synth_eval.monitoring import runner
from adaptive_synth_eval.monitoring.metric_definitions import MetricsConfig
from adaptive_synth_eval.monitoring.metric_definitions import load_metrics_config
from adaptive_synth_eval.monitoring.metrics._base import JudgeSpec


def _model_identity() -> dict[str, str]:
    return {"provider": "dry_run", "identifier": "dry_run"}


def _current_row() -> dict:
    config = load_metrics_config()
    return {
        "value_versions": {
            "resolved_model": _model_identity(),
            "metrics": {
                key: {"content_fingerprint": fingerprint, "policy_fingerprint": "policy"}
                for key, fingerprint in config.metric_content_fingerprints.items()
            },
            "metric_groups": {
                key: metric.evaluation_group for key, metric in config.metrics.items()
            },
            "group_refresh_quality": {
                group: "dry_run" for group in config.evaluation_groups
            },
        }
    }


def test_stale_groups_are_empty_for_current_row():
    config = load_metrics_config()

    assert runner._stale_groups_for_row(_current_row(), config, _model_identity()) == set()


def test_stale_groups_include_only_changed_metric_group():
    config = load_metrics_config()
    row = _current_row()
    row["value_versions"]["metrics"]["toxicity"]["content_fingerprint"] = "old"

    assert runner._stale_groups_for_row(row, config, _model_identity()) == {"safety"}


def test_stale_groups_include_all_groups_for_model_or_legacy_row():
    config = load_metrics_config()
    expected = set(config.evaluation_groups)

    assert runner._stale_groups_for_row(
        _current_row(), config, {"provider": "openai", "identifier": "judge"}
    ) == expected
    assert runner._stale_groups_for_row({}, config, _model_identity()) == expected


def test_stale_groups_cover_membership_changes_and_fallback_retry():
    config = load_metrics_config()
    row = _current_row()
    row["value_versions"]["metric_groups"]["toxicity"] = "performance"
    row["value_versions"]["metrics"]["removed"] = {"content_fingerprint": "old"}
    row["value_versions"]["metric_groups"]["removed"] = "performance"
    row["value_versions"]["group_refresh_quality"]["safety"] = "heuristic_fallback"

    assert runner._stale_groups_for_row(row, config, _model_identity()) == {
        "safety", "performance"
    }


def test_llm_scores_invert_all_risk_metrics_and_keep_positive_metrics_direct():
    config = load_metrics_config()
    responses = iter((
        '{"toxicity": 0.2, "bias_fairness": 0.4, "robustness": 0.3, "compliance": 0.25}',
        '{"relevance": 0.7, "groundedness": 0.6, "correctness": 0.8, '
        '"completeness": 0.5, "style": 0.9, "precision": 0.4}',
    ))

    class FakeLLM:
        def complete(self, _prompt):
            return SimpleNamespace(content=next(responses), error=None)

    scores, quality = runner._evaluate_with_llm(
        "question", "response", FakeLLM(), config, dry_run=False
    )

    assert scores["toxicity"] == 0.8
    assert scores["bias_fairness"] == 0.6
    assert scores["compliance"] == 0.75
    assert scores["robustness"] == 0.3
    assert scores["relevance"] == 0.7
    assert quality == {"safety": "llm", "performance": "llm"}


_VALID_SAFETY_SCORES = {
    "toxicity": 0.2,
    "bias_fairness": 0.4,
    "robustness": 0.3,
    "compliance": 0.25,
}


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="empty-object"),
        pytest.param(
            {key: value for key, value in _VALID_SAFETY_SCORES.items() if key != "toxicity"},
            id="missing-key",
        ),
        pytest.param({**_VALID_SAFETY_SCORES, "extra": 0.5}, id="extra-key"),
        pytest.param({**_VALID_SAFETY_SCORES, "toxicity": "0.2"}, id="numeric-string"),
        pytest.param({**_VALID_SAFETY_SCORES, "toxicity": True}, id="boolean"),
        pytest.param({**_VALID_SAFETY_SCORES, "toxicity": float("nan")}, id="nan"),
        pytest.param({**_VALID_SAFETY_SCORES, "toxicity": float("inf")}, id="positive-infinity"),
        pytest.param({**_VALID_SAFETY_SCORES, "toxicity": float("-inf")}, id="negative-infinity"),
        pytest.param({**_VALID_SAFETY_SCORES, "toxicity": -0.01}, id="below-range"),
        pytest.param({**_VALID_SAFETY_SCORES, "toxicity": 1.01}, id="above-range"),
    ],
)
def test_llm_group_rejects_invalid_score_objects_as_a_whole(payload):
    config = load_metrics_config()
    expected = runner._heuristic_metrics("question", "response", config)

    class FakeLLM:
        def complete(self, _prompt):
            return SimpleNamespace(content=json.dumps(payload), error=None)

    scores, quality = runner._evaluate_with_llm(
        "question", "response", FakeLLM(), config,
        dry_run=False, groups={"safety"},
    )

    safety_keys = config.metric_keys_by_group["safety"]
    assert scores == {key: expected[key] for key in safety_keys}
    assert quality == {"safety": "heuristic_fallback"}


def test_llm_group_accepts_only_valid_exact_score_object_before_inversion():
    config = load_metrics_config()

    class FakeLLM:
        def complete(self, _prompt):
            return SimpleNamespace(content=json.dumps(_VALID_SAFETY_SCORES), error=None)

    scores, quality = runner._evaluate_with_llm(
        "question", "response", FakeLLM(), config,
        dry_run=False, groups={"safety"},
    )

    assert scores == {
        "toxicity": 0.8,
        "bias_fairness": 0.6,
        "robustness": 0.3,
        "compliance": 0.75,
    }
    assert quality == {"safety": "llm"}


def test_group_messages_separate_rubrics_from_untrusted_reference_payload():
    config = load_metrics_config()
    metrics = [
        config.metrics[key]
        for key in ("groundedness", "completeness")
    ]

    system_prompt, user_payload = runner._build_group_messages(
        "performance",
        metrics,
        user_text="What does the policy require?",
        response_text="It requires approval.",
        reference_context="Policy section 4 requires manager approval.",
        reference_answer="Manager approval is required.",
    )

    assert "exactly these keys" in system_prompt
    assert json.dumps(["groundedness", "completeness"]) in system_prompt
    assert "Policy section 4" not in system_prompt
    assert "untrusted data" in system_prompt
    payload = json.loads(user_payload)
    assert payload == {
        "user_message": "What does the policy require?",
        "chatbot_response": "It requires approval.",
        "reference_context": "Policy section 4 requires manager approval.",
        "reference_answer": "Manager approval is required.",
    }


def test_group_messages_omit_irrelevant_or_empty_references():
    config = load_metrics_config()
    safety_metrics = [
        config.metrics[key] for key in config.metric_keys_by_group["safety"]
    ]

    _, user_payload = runner._build_group_messages(
        "safety",
        safety_metrics,
        user_text="question",
        response_text="answer",
        reference_context="ignored context",
        reference_answer="ignored answer",
    )

    assert json.loads(user_payload) == {
        "user_message": "question",
        "chatbot_response": "answer",
    }
    assert runner._reference_modes(None, "  ") == {
        "groundedness": "query_only",
        "completeness": "query_only",
    }
    assert runner._reference_modes("context", "answer") == {
        "groundedness": "reference_backed",
        "completeness": "reference_backed",
    }


def test_reference_inputs_prefer_canonical_fields_and_accept_external_aliases():
    assert runner._reference_inputs({
        "reference_context": " canonical context ",
        "context": "alias context",
        "reference_answer": " canonical answer ",
        "ground_truth": "alias answer",
    }) == ("canonical context", "canonical answer")
    assert runner._reference_inputs({
        "context": "alias context",
        "ground_truth": "alias answer",
    }) == ("alias context", "alias answer")
    assert runner._reference_inputs({
        "reference_context": {"not": "a string"},
        "ground_truth": [],
    }) == (None, None)


def test_build_judge_batches_partitions_by_group_and_metric_route(tmp_path):
    path = tmp_path / "metrics.yaml"
    path.write_text(
        """
metrics:
  toxicity:
    evaluation_group: safety
    label: Toxicity
    description: Toxicity.
    detail: Toxicity detail.
    eval_input_key: toxicity
    thresholds: {warn_below: 85, fail_below: 65}
    judge: {provider: openai, model: gpt-judge}
  relevance:
    evaluation_group: performance
    label: Relevance
    description: Relevance.
    detail: Relevance detail.
    eval_input_key: relevance
    thresholds: {warn_below: 85, fail_below: 60}
  groundedness:
    evaluation_group: performance
    label: Groundedness
    description: Groundedness.
    detail: Groundedness detail.
    eval_input_key: groundedness
    thresholds: {warn_below: 80, fail_below: 55}
    judge: {provider: openai, model: gpt-judge}
  correctness:
    evaluation_group: performance
    label: Correctness
    description: Correctness.
    detail: Correctness detail.
    eval_input_key: correctness
    thresholds: {warn_below: 65, fail_below: 40}
    judge: {provider: openai, model: gpt-judge, api_key_env: OTHER_JUDGE_KEY}
llm_evaluation:
  prompt_template: Evaluate this metric using normalized anchors.
""".strip(),
        encoding="utf-8",
    )
    config = load_metrics_config(path)
    default_llm = LLMClient(
        enabled=True,
        model_provider="anthropic",
        config={"model": "claude-judge"},
    )

    batches = runner._build_judge_batches(
        config,
        default_llm=default_llm,
        dry_run=False,
    )

    assert [
               (batch.group_name, batch.metric_keys, batch.judge_identity)
               for batch in batches
           ] == [
               (
                   "performance",
                   ("relevance",),
                   {"provider": "anthropic", "identifier": "claude-judge"},
               ),
               (
                   "performance",
                   ("groundedness",),
                   {"provider": "openai", "identifier": "gpt-judge"},
               ),
               (
                   "performance",
                   ("correctness",),
                   {"provider": "openai", "identifier": "gpt-judge"},
               ),
               (
                   "safety",
                   ("toxicity",),
                   {"provider": "openai", "identifier": "gpt-judge"},
               ),
           ]
    override_clients = [batch.llm for batch in batches if batch.llm is not default_llm]
    assert len({id(client) for client in override_clients}) == 2
    for client in override_clients:
        assert client.config["temperature"] == 0.0
        assert client.config["top_p"] == 1.0
        assert client.config["max_tokens"] == 800


def test_dry_run_fingerprint_retains_configured_metric_route_without_live_client():
    original = load_metrics_config()
    metrics = dict(original.metrics)
    metrics["toxicity"] = replace(
        metrics["toxicity"],
        judge=JudgeSpec(provider="openai", model="configured-judge"),
    )
    config = MetricsConfig(
        metrics=metrics,
        metric_content_fingerprints=original.metric_content_fingerprints,
        evaluation_groups=original.evaluation_groups,
        metric_keys_by_group=original.metric_keys_by_group,
    )
    default_llm = LLMClient(enabled=False)

    batches = runner._build_judge_batches(
        config,
        default_llm=default_llm,
        dry_run=True,
    )

    toxicity_batch = next(batch for batch in batches if "toxicity" in batch.metric_keys)
    bias_batch = next(batch for batch in batches if "bias_fairness" in batch.metric_keys)
    assert toxicity_batch.judge_fingerprint != bias_batch.judge_fingerprint
    assert toxicity_batch.llm is default_llm
    assert toxicity_batch.judge_identity == {
        "provider": "dry_run",
        "identifier": "dry_run",
    }


def test_evaluate_judge_batches_isolates_partial_provider_failure():
    config = load_metrics_config()

    class FakeLLM:
        def __init__(self, content=None, error=None):
            self.content = content
            self.error = error
            self.calls = []

        def complete(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            return SimpleNamespace(content=self.content or "", error=self.error)

    successful = FakeLLM('{"toxicity": 0.2, "bias_fairness": 0.4}')
    failed = FakeLLM(error="provider unavailable")
    batches = [
        runner.JudgeBatch(
            batch_id="safe-a",
            group_name="safety",
            metric_keys=("toxicity", "bias_fairness"),
            llm=successful,
            judge_identity={"provider": "openai", "identifier": "judge-a"},
            judge_fingerprint="fp-a",
        ),
        runner.JudgeBatch(
            batch_id="safe-b",
            group_name="safety",
            metric_keys=("robustness", "compliance"),
            llm=failed,
            judge_identity={"provider": "anthropic", "identifier": "judge-b"},
            judge_fingerprint="fp-b",
        ),
    ]

    outcome = runner._evaluate_judge_batches(
        "question",
        "response",
        metrics_config=config,
        batches=batches,
        dry_run=False,
    )

    heuristic = runner._heuristic_metrics("question", "response", config)
    assert outcome.scores["toxicity"] == 0.8
    assert outcome.scores["bias_fairness"] == 0.6
    assert outcome.scores["robustness"] == heuristic["robustness"]
    assert outcome.scores["compliance"] == heuristic["compliance"]
    assert outcome.batch_quality == {
        "safe-a": "llm",
        "safe-b": "heuristic_fallback",
    }
    assert outcome.group_quality == {"safety": "mixed"}
    payload, kwargs = successful.calls[0]
    assert set(json.loads(payload)) == {"user_message", "chatbot_response"}
    assert kwargs["json_mode"] is True
    assert "toxicity" in kwargs["system_prompt"]
    assert "robustness" not in kwargs["system_prompt"]


def test_stale_judge_batches_track_inputs_and_failed_batch_only():
    config = load_metrics_config()
    default_llm = LLMClient(enabled=False)
    batches = runner._build_judge_batches(
        config,
        default_llm=default_llm,
        dry_run=True,
    )
    quality = {batch.batch_id: "dry_run" for batch in batches}
    row = {
        "value_versions": {
            "metrics": {
                key: {
                    "content_fingerprint": fingerprint,
                    "policy_fingerprint": "policy",
                }
                for key, fingerprint in config.metric_content_fingerprints.items()
            },
            "judge_batches": runner._judge_batch_versions(
                batches,
                quality,
                user_text="question",
                response_text="answer",
                reference_context="context-v1",
                reference_answer="reference-v1",
            ),
        }
    }

    assert runner._stale_batch_ids_for_row(
        row,
        config,
        batches,
        user_text="question",
        response_text="answer",
        reference_context="context-v1",
        reference_answer="reference-v1",
    ) == set()

    changed_reference = runner._stale_batch_ids_for_row(
        row,
        config,
        batches,
        user_text="question",
        response_text="answer",
        reference_context="context-v2",
        reference_answer="reference-v1",
    )
    assert changed_reference == {
        batch.batch_id for batch in batches if batch.group_name == "performance"
    }

    safety = next(batch for batch in batches if batch.group_name == "safety")
    row["value_versions"]["judge_batches"][safety.batch_id]["refresh_quality"] = (
        "heuristic_fallback"
    )
    stale = runner._stale_batch_ids_for_row(
        row,
        config,
        batches,
        user_text="question",
        response_text="answer",
        reference_context="context-v1",
        reference_answer="reference-v1",
    )
    assert stale == {safety.batch_id}


def test_load_monitoring_state_reads_existing_json(tmp_path):
    state = {"status": "completed", "next_line_index": 3}
    (tmp_path / "monitoring_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    assert runner._load_monitoring_state(tmp_path) == state
