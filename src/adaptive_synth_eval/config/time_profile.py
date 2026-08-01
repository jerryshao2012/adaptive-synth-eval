"""Shared parsing, validation, and serialization for time-based profiles."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from adaptive_synth_eval.config.schemas import TimeProfile, TimeProfileWindow

ALLOWED_BEHAVIOR_MODES = frozenset(
    {
        "default",
        "aggressive",
        "polite",
        "concise",
        "confused",
        "anxious",
        "stressed",
        "toxic",
    }
)
_HH_MM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class TimeProfileError(ValueError):
    """Raised when a time profile is malformed or inconsistent."""


def parse_time_profile(payload: Any) -> TimeProfile | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise TimeProfileError("time_profile must be a mapping")
    raw_windows = payload.get("windows")
    if not isinstance(raw_windows, list):
        raise TimeProfileError("time_profile.windows must be a list")

    windows: list[TimeProfileWindow] = []
    for index, raw in enumerate(raw_windows):
        if not isinstance(raw, Mapping):
            raise TimeProfileError(f"time_profile.windows[{index}] must be a mapping")
        missing = [
            key
            for key in (
                "period_id",
                "start_time",
                "end_time",
                "traffic_weight",
                "recipe_weights",
            )
            if key not in raw
        ]
        if missing:
            raise TimeProfileError(
                f"time_profile.windows[{index}] missing required field(s): {', '.join(missing)}"
            )
        recipe_weights = raw["recipe_weights"]
        if not isinstance(recipe_weights, Mapping):
            raise TimeProfileError(
                f"time_profile.windows[{index}].recipe_weights must be a mapping"
            )
        try:
            parsed_weights = {
                str(recipe_id): float(weight)
                for recipe_id, weight in recipe_weights.items()
            }
            traffic_weight = float(raw["traffic_weight"])
        except (TypeError, ValueError) as exc:
            raise TimeProfileError(
                f"time_profile.windows[{index}] weights must be numeric"
            ) from exc
        period_id = _non_empty_string(
            raw["period_id"], field=f"time_profile.windows[{index}].period_id"
        )
        conversation_mode = _non_empty_string(
            raw.get("conversation_mode", "default"),
            field=f"time_profile.windows[{index}].conversation_mode",
        )
        windows.append(
            TimeProfileWindow(
                period_id=period_id,
                start_time=str(raw["start_time"]),
                end_time=str(raw["end_time"]),
                traffic_weight=traffic_weight,
                conversation_mode=conversation_mode,
                behavior_mode=str(raw.get("behavior_mode", "default")),
                recipe_weights=parsed_weights,
            )
        )
    return TimeProfile(windows=tuple(windows))


def validate_time_profile(
    profile: TimeProfile | None,
    *,
    recipes: Iterable[object],
    total_conversations: int | None,
    num_synthetic_days: int,
    unbounded: bool = False,
) -> None:
    if profile is None:
        return
    if num_synthetic_days <= 0:
        raise TimeProfileError("num_synthetic_days must be greater than 0 for time_profile")
    if len(profile.windows) < 2:
        raise TimeProfileError("time_profile requires at least 2 windows")

    period_ids: set[str] = set()
    previous_end: int | None = None
    for index, window in enumerate(profile.windows):
        period_id = window.period_id.strip()
        if not period_id:
            raise TimeProfileError("time_profile period_id must be non-empty")
        if period_id in period_ids:
            raise TimeProfileError("time_profile period_id values must be unique")
        period_ids.add(period_id)

        start = _minute_of_day(window.start_time, field="start_time", index=index)
        end = _minute_of_day(window.end_time, field="end_time", index=index)
        if start >= end:
            raise TimeProfileError(
                f"time_profile.windows[{index}] start_time must be before end_time"
            )
        if previous_end is not None and start < previous_end:
            raise TimeProfileError(
                "time_profile windows must be strictly ordered and must not overlap"
            )
        previous_end = end

        if not math.isfinite(window.traffic_weight) or window.traffic_weight <= 0:
            raise TimeProfileError("time_profile traffic_weight must be greater than 0")
        if not window.conversation_mode.strip():
            raise TimeProfileError("time_profile conversation_mode must be non-empty")
        if window.behavior_mode not in ALLOWED_BEHAVIOR_MODES:
            allowed = ", ".join(sorted(ALLOWED_BEHAVIOR_MODES))
            raise TimeProfileError(f"time_profile behavior_mode must be one of {allowed}")
        if not window.recipe_weights:
            raise TimeProfileError("time_profile recipe_weights must be non-empty")
        if any(not recipe_id.strip() for recipe_id in window.recipe_weights):
            raise TimeProfileError("time_profile recipe_weights keys must be non-empty")
        if any(
            not math.isfinite(weight) or weight < 0
            for weight in window.recipe_weights.values()
        ):
            raise TimeProfileError(
                "time_profile recipe_weights must not contain negative or non-finite values"
            )
        if not any(weight > 0 for weight in window.recipe_weights.values()):
            raise TimeProfileError(
                "time_profile recipe_weights must contain at least one positive value"
            )

    recipe_ids: list[str] = []
    for recipe in recipes:
        raw_recipe_id = getattr(recipe, "recipe_id", None)
        if not isinstance(raw_recipe_id, str) or not raw_recipe_id.strip():
            raise TimeProfileError(
                "all recipes must define a non-empty recipe_id when time_profile is present"
            )
        recipe_ids.append(raw_recipe_id.strip())
    if len(set(recipe_ids)) != len(recipe_ids):
        raise TimeProfileError(
            "all recipes must define unique recipe_id values when time_profile is present"
        )
    known_recipe_ids = set(recipe_ids)
    referenced_recipe_ids = {
        recipe_id for window in profile.windows for recipe_id in window.recipe_weights
    }
    unknown = sorted(referenced_recipe_ids - known_recipe_ids)
    if unknown:
        raise TimeProfileError(
            f"time_profile references unknown recipe_id(s): {', '.join(unknown)}"
        )

    if unbounded or total_conversations is None:
        raise TimeProfileError(
            "time_profile requires a finite total_conversations; unbounded runs are not supported"
        )
    minimum = num_synthetic_days * len(profile.windows)
    if total_conversations < minimum:
        raise TimeProfileError(
            f"total_conversations must be at least {minimum} for time_profile period coverage"
        )


def time_profile_to_dict(profile: TimeProfile) -> dict[str, Any]:
    return {
        "windows": [
            {
                "period_id": window.period_id,
                "start_time": window.start_time,
                "end_time": window.end_time,
                "traffic_weight": window.traffic_weight,
                "conversation_mode": window.conversation_mode,
                "behavior_mode": window.behavior_mode,
                "recipe_weights": dict(window.recipe_weights),
            }
            for window in profile.windows
        ]
    }


def _minute_of_day(value: str, *, field: str, index: int) -> int:
    if not _HH_MM.fullmatch(value):
        raise TimeProfileError(
            f"time_profile.windows[{index}].{field} must use same-day HH:MM format"
        )
    hours, minutes = (int(part) for part in value.split(":"))
    return hours * 60 + minutes


def _non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TimeProfileError(f"{field} must be a non-empty string")
    return value
