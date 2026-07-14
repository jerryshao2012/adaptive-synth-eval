"""Unit tests for selective monitoring-score refresh behavior."""

from copy import deepcopy

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
