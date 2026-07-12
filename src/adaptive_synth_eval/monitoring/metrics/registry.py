from __future__ import annotations

from pathlib import Path

import yaml

from adaptive_synth_eval.monitoring.fingerprint import compute_metric_content_fingerprint
from ._base import MetricSpec


class MetricRegistry:
    """Discovers, loads, and manages per-metric YAML specifications."""

    def __init__(self, metrics_dir: Path | None = None):
        self._metrics_dir = metrics_dir or Path(__file__).resolve().parent
        self._specs: dict[str, MetricSpec] = {}
        self._load_all()

    def _load_all(self) -> None:
        for yaml_file in sorted(self._metrics_dir.glob("*.yaml")):
            with yaml_file.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            key = data["key"]
            evaluation_group = data["evaluation_group"]
            label = data["label"]
            description = data["description"]
            detail = data["detail"]
            eval_input_key = data["eval_input_key"]
            warn_below = float(data["warn_below"])
            fail_below = float(data["fail_below"])
            invert_llm_score = bool(data.get("invert_llm_score", False))
            prompt_template = data["prompt_template"]

            # Validate threshold ordering.
            if fail_below >= warn_below:
                raise ValueError(
                    f"Metric '{key}' in {yaml_file.name}: fail_below ({fail_below}) "
                    f"must be less than warn_below ({warn_below})."
                )

            # Process optional heuristics config (stored as raw dict).
            h_data = data.get("heuristic")
            h_rule: dict | None = None
            if isinstance(h_data, dict):
                h_rule = h_data

            # Compute the per-metric content fingerprint.
            content_fp = compute_metric_content_fingerprint(
                metric_key=key,
                prompt_template=prompt_template,
                eval_input_key=eval_input_key,
                invert_llm_score=invert_llm_score,
                warn_below=warn_below,
                fail_below=fail_below,
                heuristic=h_rule,
            )

            spec = MetricSpec(
                key=key,
                evaluation_group=evaluation_group,
                label=label,
                description=description,
                detail=detail,
                eval_input_key=eval_input_key,
                warn_below=warn_below,
                fail_below=fail_below,
                invert_llm_score=invert_llm_score,
                prompt_template=prompt_template,
                heuristic=h_rule,
                content_fingerprint=content_fp,
            )
            self._specs[spec.key] = spec

    def get(self, key: str) -> MetricSpec:
        if key not in self._specs:
            raise KeyError(f"Metric '{key}' not found in registry.")
        return self._specs[key]

    def all_specs(self) -> dict[str, MetricSpec]:
        return dict(self._specs)

    def by_group(self, group: str) -> list[MetricSpec]:
        return [spec for spec in self._specs.values() if spec.evaluation_group == group]
