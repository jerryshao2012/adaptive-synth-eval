"""Unit tests for selective monitoring-score refresh behavior."""

import json
from types import SimpleNamespace

import pytest

from adaptive_synth_eval.monitoring import runner
from adaptive_synth_eval.monitoring.metric_definitions import load_metrics_config


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
