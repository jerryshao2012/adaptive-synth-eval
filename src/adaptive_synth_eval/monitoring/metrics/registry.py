from __future__ import annotations

import math
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import yaml

from adaptive_synth_eval.monitoring.fingerprint import (
    compute_metric_content_fingerprint,
)

from ._base import MetricSpec, parse_judge_spec


def _reject_unknown_fields(
    value: dict,
    *,
    allowed: set[str],
    context: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unknown fields: {', '.join(unknown)}.")


def _finite_number(
    value: object,
    *,
    filename: str,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise ValueError(
            f"Metric specification {filename} heuristic {field_name} "
            "must be a finite number."
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Metric specification {filename} heuristic {field_name} "
            "must be a finite number."
        ) from exc
    if not math.isfinite(number):
        raise ValueError(
            f"Metric specification {filename} heuristic {field_name} "
            "must be a finite number."
        )
    return number


def _unit_interval(
    value: object,
    *,
    filename: str,
    field_name: str,
) -> float:
    number = _finite_number(value, filename=filename, field_name=field_name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(
            f"Metric specification {filename} heuristic {field_name} "
            "must be between 0 and 1."
        )
    return number


def _validate_heuristic(filename: str, heuristic: dict) -> None:
    heuristic_type = heuristic.get("type")
    if heuristic_type is not None and not isinstance(heuristic_type, str):
        raise ValueError(
            f"Metric specification {filename} heuristic type must be a string."
        )

    if heuristic_type == "overlap":
        _reject_unknown_fields(
            heuristic,
            allowed={"type", "offset"},
            context=f"Metric specification {filename} heuristic",
        )
        if "offset" in heuristic:
            _finite_number(heuristic["offset"], filename=filename, field_name="offset")
        return

    if heuristic_type == "length_ratio":
        _reject_unknown_fields(
            heuristic,
            allowed={"type", "base", "divisor"},
            context=f"Metric specification {filename} heuristic",
        )
        if "base" in heuristic:
            _finite_number(heuristic["base"], filename=filename, field_name="base")
        if "divisor" in heuristic:
            divisor = _finite_number(
                heuristic["divisor"], filename=filename, field_name="divisor"
            )
            if divisor <= 0.0:
                raise ValueError(
                    f"Metric specification {filename} heuristic length_ratio "
                    "divisor must be greater than zero."
                )
        return

    if heuristic_type == "style":
        _reject_unknown_fields(
            heuristic,
            allowed={"type", "default_score", "empty_score"},
            context=f"Metric specification {filename} heuristic",
        )
        for field_name in ("default_score", "empty_score"):
            if field_name in heuristic:
                _unit_interval(
                    heuristic[field_name],
                    filename=filename,
                    field_name=field_name,
                )
        return

    if heuristic_type is not None:
        raise ValueError(
            f"Metric specification {filename} heuristic type "
            f"'{heuristic_type}' is not supported."
        )

    _reject_unknown_fields(
        heuristic,
        allowed={"default_score", "keyword_penalties"},
        context=f"Metric specification {filename} heuristic",
    )
    if "default_score" in heuristic:
        _unit_interval(
            heuristic["default_score"],
            filename=filename,
            field_name="default_score",
        )
    penalties = heuristic.get("keyword_penalties", [])
    if not isinstance(penalties, list):
        raise ValueError(
            f"Metric specification {filename} heuristic keyword_penalties "
            "must be a list."
        )
    for index, penalty in enumerate(penalties):
        prefix = f"keyword_penalties[{index}]"
        if not isinstance(penalty, dict):
            raise ValueError(
                f"Metric specification {filename} heuristic {prefix} must be a mapping."
            )
        _reject_unknown_fields(
            penalty,
            allowed={"keywords", "score"},
            context=f"Metric specification {filename} heuristic {prefix}",
        )
        keywords = penalty.get("keywords")
        if not isinstance(keywords, list):
            raise ValueError(
                f"Metric specification {filename} heuristic {prefix} "
                "keywords must be a list."
            )
        if not keywords or any(
            not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
        ):
            raise ValueError(
                f"Metric specification {filename} heuristic {prefix} keywords "
                "must contain non-empty strings."
            )
        if "score" not in penalty:
            raise ValueError(
                f"Metric specification {filename} heuristic {prefix} must define score."
            )
        _unit_interval(
            penalty["score"], filename=filename, field_name=f"{prefix} score"
        )


class MetricRegistry:
    """Discovers, loads, and manages per-metric YAML specifications."""

    def __init__(self, metrics_dir: Path | Traversable | None = None):
        self._metrics_dir = metrics_dir or resources.files(
            "adaptive_synth_eval.monitoring.metrics"
        )
        self._specs: dict[str, MetricSpec] = {}
        self._load_all()

    def _load_all(self) -> None:
        yaml_files = sorted(
            (
                entry
                for entry in self._metrics_dir.iterdir()
                if entry.is_file() and entry.name.endswith(".yaml")
            ),
            key=lambda entry: entry.name,
        )
        for yaml_file in yaml_files:
            with yaml_file.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ValueError(
                    f"Metric specification {yaml_file.name} must contain a mapping."
                )

            _reject_unknown_fields(
                data,
                allowed={
                    "key",
                    "evaluation_group",
                    "label",
                    "description",
                    "detail",
                    "eval_input_key",
                    "warn_below",
                    "fail_below",
                    "invert_llm_score",
                    "prompt_template",
                    "heuristic",
                    "judge",
                },
                context=f"Metric specification {yaml_file.name}",
            )

            required_fields = (
                "key",
                "evaluation_group",
                "label",
                "description",
                "detail",
                "eval_input_key",
                "warn_below",
                "fail_below",
                "prompt_template",
            )
            for field_name in required_fields:
                if field_name not in data:
                    raise ValueError(
                        f"Metric specification {yaml_file.name} is missing "
                        f"required field '{field_name}'."
                    )

            string_fields = (
                "key",
                "evaluation_group",
                "label",
                "description",
                "detail",
                "eval_input_key",
                "prompt_template",
            )
            for field_name in string_fields:
                value = data[field_name]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"Metric specification {yaml_file.name} {field_name} "
                        "must be a non-empty string."
                    )
                data[field_name] = value.strip()

            key = data["key"]
            evaluation_group = data["evaluation_group"]
            label = data["label"]
            description = data["description"]
            detail = data["detail"]
            eval_input_key = data["eval_input_key"]
            if isinstance(data["warn_below"], bool) or isinstance(
                data["fail_below"], bool
            ):
                raise ValueError(
                    f"Metric specification {yaml_file.name} thresholds must be numeric."
                )
            try:
                warn_below = float(data["warn_below"])
                fail_below = float(data["fail_below"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Metric specification {yaml_file.name} thresholds must be numeric."
                ) from exc
            if (
                not math.isfinite(warn_below)
                or not math.isfinite(fail_below)
                or not 0.0 <= warn_below <= 100.0
                or not 0.0 <= fail_below <= 100.0
            ):
                raise ValueError(
                    f"Metric specification {yaml_file.name} thresholds must be "
                    "between 0 and 100."
                )
            invert_value = data.get("invert_llm_score", False)
            if not isinstance(invert_value, bool):
                raise ValueError(
                    f"Metric specification {yaml_file.name} invert_llm_score "
                    "must be a boolean."
                )
            invert_llm_score = invert_value
            prompt_template = data["prompt_template"]
            judge = parse_judge_spec(data.get("judge"), metric_key=key)

            # Validate threshold ordering.
            if fail_below >= warn_below:
                raise ValueError(
                    f"Metric '{key}' in {yaml_file.name}: fail_below ({fail_below}) "
                    f"must be less than warn_below ({warn_below})."
                )

            # Process optional heuristics config (stored as raw dict).
            h_data = data.get("heuristic")
            if h_data is not None and not isinstance(h_data, dict):
                raise ValueError(
                    f"Metric specification {yaml_file.name} heuristic must be a mapping."
                )
            h_rule: dict | None = None
            if isinstance(h_data, dict):
                _validate_heuristic(yaml_file.name, h_data)
                h_rule = h_data

            # Compute the per-metric content fingerprint.
            content_fp = compute_metric_content_fingerprint(
                metric_key=key,
                prompt_template=prompt_template,
                eval_input_key=eval_input_key,
                invert_llm_score=invert_llm_score,
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
                judge=judge,
            )
            if spec.key in self._specs:
                raise ValueError(
                    f"Duplicate metric key '{spec.key}' in {yaml_file.name}."
                )
            self._specs[spec.key] = spec

        if not self._specs:
            raise ValueError(f"No metric specifications found in {self._metrics_dir}.")

    def get(self, key: str) -> MetricSpec:
        if key not in self._specs:
            raise KeyError(f"Metric '{key}' not found in registry.")
        return self._specs[key]

    def all_specs(self) -> dict[str, MetricSpec]:
        return dict(self._specs)

    def by_group(self, group: str) -> list[MetricSpec]:
        return [spec for spec in self._specs.values() if spec.evaluation_group == group]
