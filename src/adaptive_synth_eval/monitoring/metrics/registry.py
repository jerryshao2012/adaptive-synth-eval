from __future__ import annotations

from pathlib import Path

import yaml

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

            # Process optional heuristics config
            h_data = data.get("heuristic")
            h_rule = None
            if isinstance(h_data, dict):
                # Safety-style safety rules or custom ones
                default_val = h_data.get("default_score", 1.0)
                penalties = h_data.get("keyword_penalties")
                # We store the raw dict or standard rules
                h_rule = h_data

            spec = MetricSpec(
                key=data["key"],
                evaluation_group=data["evaluation_group"],
                label=data["label"],
                description=data["description"],
                detail=data["detail"],
                eval_input_key=data["eval_input_key"],
                warn_below=float(data["warn_below"]),
                fail_below=float(data["fail_below"]),
                invert_llm_score=bool(data.get("invert_llm_score", False)),
                version=str(data["version"]),
                prompt_template=data["prompt_template"],
                heuristic=h_rule,
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
