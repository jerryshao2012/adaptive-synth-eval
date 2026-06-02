"""
Optional MLflow observability for the adversarial evaluation harness.

Enabled by setting MLFLOW_TRACKING_URI in the environment.
If the env var is absent or mlflow is not installed, NullObserver is used
and the harness behaves identically to running without this module.
"""
from __future__ import annotations

import os
from typing import Dict, Any


class NullObserver:
    """No-op observer — the safe default when MLflow is not configured."""

    def start_run(self, params: Dict[str, Any]) -> None:
        pass

    def log_turn_metrics(self, judge_result: Dict[str, Any], step: int) -> None:
        pass

    def finish_run(self, summary: Dict[str, Any], artifact_path: str | None = None) -> None:
        pass


class MLflowObserver:
    """
    Logs experiment params, per-turn step metrics, summary scalars, and the
    results artifact to an MLflow tracking server.

    One MLflow experiment per scenario_type (e.g. "adversarial-eval/toxicity").
    One MLflow run per call to run_single().
    """

    def __init__(
            self,
            scenario_type: str,
            model_label: str,
            prefix: str = "adversarial-eval",
    ) -> None:
        import mlflow
        self._mlflow = mlflow
        mlflow.set_experiment(f"{prefix}/{scenario_type}")
        self._model_label = model_label

    def start_run(self, params: Dict[str, Any]) -> None:
        self._mlflow.start_run(run_name=self._model_label)
        # MLflow requires all param values to be strings
        str_params = {k: str(v) for k, v in params.items()}
        self._mlflow.log_params(str_params)

    def log_turn_metrics(self, judge_result: Dict[str, Any], step: int) -> None:
        self._mlflow.log_metrics(
            {
                "failure_score": float(judge_result.get("failure_score", 0)),
                "harm_potential": float(judge_result.get("harm_potential", 0)),
                "specificity": float(judge_result.get("specificity", 0)),
                "refusal_quality": float(judge_result.get("refusal_quality", 0)),
            },
            step=step,
        )

    def finish_run(self, summary: Dict[str, Any], artifact_path: str | None = None) -> None:
        numeric = {
            k: float(v)
            for k, v in summary.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        if numeric:
            self._mlflow.log_metrics(numeric)
        if artifact_path and os.path.exists(artifact_path):
            self._mlflow.log_artifact(artifact_path)
        self._mlflow.end_run()


def make_observer(scenario_type: str, model_label: str) -> NullObserver | MLflowObserver:
    """
    Return an MLflowObserver if MLFLOW_TRACKING_URI is set and mlflow is
    importable; otherwise return a NullObserver.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if not uri:
        return NullObserver()
    try:
        import mlflow
        mlflow.set_tracking_uri(uri)
        return MLflowObserver(scenario_type, model_label)
    except ImportError:
        return NullObserver()
