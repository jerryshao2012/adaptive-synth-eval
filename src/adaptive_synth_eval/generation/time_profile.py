"""Deterministic conversation planning for shared time profiles."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Callable, Generic, Sequence, TypeVar

from adaptive_synth_eval.config.schemas import TimeProfile, TimeProfileWindow, TimeWindow

RecipeT = TypeVar("RecipeT")


@dataclass(frozen=True)
class PlannedProfileConversation(Generic[RecipeT]):
    recipe: RecipeT
    recipe_id: str
    synthetic_timestamp: datetime
    synthetic_slot: int
    profile_period_id: str
    instance_id: str
    start: datetime
    end: datetime
    conversation_mode: str
    behavior_mode: str
    traffic_weight: float
    recipe_weights: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Return the serializable planning metadata for this conversation."""

        return {
            "recipe_id": self.recipe_id,
            "synthetic_timestamp": self.synthetic_timestamp.isoformat(),
            "synthetic_slot": self.synthetic_slot,
            "profile_period_id": self.profile_period_id,
            "instance_id": self.instance_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "conversation_mode": self.conversation_mode,
            "behavior_mode": self.behavior_mode,
            "traffic_weight": self.traffic_weight,
            "recipe_weights": dict(self.recipe_weights),
        }


@dataclass(frozen=True)
class _WindowInstance:
    window: TimeProfileWindow
    instance_id: str
    start: datetime
    end: datetime


def build_time_profile_plan(
    *,
    profile: TimeProfile,
    time_window: TimeWindow,
    total_conversations: int,
    recipes: Sequence[RecipeT],
    random_seed: int | None = None,
    recipe_id_getter: Callable[[RecipeT], str | None] | None = None,
) -> list[PlannedProfileConversation[RecipeT]]:
    """Allocate a finite run across recurring windows and choose active recipes.

    Contract loading performs full profile validation. This function still checks the
    two invariants needed for safe standalone use: finite coverage and resolvable IDs.
    """

    instances = _window_instances(profile, time_window)
    if total_conversations < len(instances):
        raise ValueError(
            "total_conversations must provide at least one conversation per window instance"
        )
    getter = recipe_id_getter or (lambda recipe: getattr(recipe, "recipe_id", None))
    recipes_by_id: dict[str, RecipeT] = {}
    for recipe in recipes:
        raw_recipe_id = getter(recipe)
        if not isinstance(raw_recipe_id, str) or not raw_recipe_id.strip():
            raise ValueError("recipes must have non-empty recipe_id values")
        recipe_id = raw_recipe_id.strip()
        if recipe_id in recipes_by_id:
            raise ValueError(f"duplicate recipe_id: {recipe_id}")
        recipes_by_id[recipe_id] = recipe

    allocations = _allocate_instances(instances, total_conversations)
    rng = random.Random(0 if random_seed is None else random_seed)
    plan: list[PlannedProfileConversation[RecipeT]] = []
    for instance, count in zip(instances, allocations):
        active = [
            (recipe_id, weight)
            for recipe_id, weight in instance.window.recipe_weights.items()
            if weight > 0
        ]
        missing = [recipe_id for recipe_id, _ in active if recipe_id not in recipes_by_id]
        if missing:
            raise ValueError(f"unknown profile recipe_id(s): {', '.join(sorted(missing))}")
        for slot in range(1, count + 1):
            recipe_id = _weighted_recipe_id(active, rng)
            timestamp = instance.start + (instance.end - instance.start) * (
                slot / (count + 1)
            )
            plan.append(
                PlannedProfileConversation(
                    recipe=recipes_by_id[recipe_id],
                    recipe_id=recipe_id,
                    synthetic_timestamp=timestamp,
                    synthetic_slot=slot,
                    profile_period_id=instance.window.period_id,
                    instance_id=instance.instance_id,
                    start=instance.start,
                    end=instance.end,
                    conversation_mode=instance.window.conversation_mode,
                    behavior_mode=instance.window.behavior_mode,
                    traffic_weight=instance.window.traffic_weight,
                    recipe_weights=instance.window.recipe_weights,
                )
            )
    return plan


def profile_turn_timestamp(
    planned: Any, *, turn_id: int, turn_count: int
) -> datetime:
    """Return a deterministic increasing turn time without crossing the period end."""

    def value(name: str) -> Any:
        if isinstance(planned, Mapping):
            return planned[name]
        return getattr(planned, name)

    base = value("synthetic_timestamp")
    period_end = value("profile_period_end")
    remaining_seconds = max(0.0, (period_end - base).total_seconds())
    interval_seconds = min(1.0, remaining_seconds / max(1, int(turn_count)))
    return min(
        base + timedelta(seconds=max(0, int(turn_id) - 1) * interval_seconds),
        period_end,
    )


def resolve_behavior_override(
    planned_behavior: str | None,
    realtime_controller: Any | None,
    persona_id: str,
) -> str | None:
    """Prefer an explicitly selected live style over the planned profile style."""

    if realtime_controller is not None:
        explicit_getter = getattr(
            realtime_controller, "get_behavior_override_for_persona", None
        )
        if callable(explicit_getter):
            live = explicit_getter(persona_id)
            if live is not None:
                return live
        else:
            legacy_getter = getattr(
                realtime_controller, "get_behavior_for_persona", None
            )
            if callable(legacy_getter):
                return legacy_getter(persona_id)
    return planned_behavior


def profile_provenance(planned: Any) -> dict[str, Any]:
    """Serialize the shared provenance carried by a profiled plan row."""

    def value(name: str) -> Any:
        if isinstance(planned, Mapping):
            return planned[name]
        return getattr(planned, name)

    metadata = {
        "recipe_id": value("recipe_id"),
        "synthetic_timestamp": value("synthetic_timestamp").isoformat(),
        "synthetic_slot": value("synthetic_slot"),
        "profile_period_id": value("profile_period_id"),
        "profile_period_instance_id": value("profile_period_instance_id"),
        "profile_period_start": value("profile_period_start").isoformat(),
        "profile_period_end": value("profile_period_end").isoformat(),
        "conversation_mode": value("conversation_mode"),
        "behavior_mode": value("behavior_mode"),
        "traffic_weight": value("traffic_weight"),
        "recipe_weights": dict(value("recipe_weights")),
    }
    sequence = (
        planned.get("sequence")
        if isinstance(planned, Mapping)
        else getattr(planned, "sequence", None)
    )
    if sequence is not None:
        metadata["sequence"] = int(sequence)
    return metadata


def profile_turn_provenance(
    planned: Any, *, turn_id: int, turn_count: int
) -> dict[str, Any]:
    metadata = profile_provenance(planned)
    metadata["timestamp"] = profile_turn_timestamp(
        planned, turn_id=turn_id, turn_count=turn_count
    ).isoformat()
    return metadata


def summarize_profile_plan(plan: Sequence[Any]) -> dict[str, dict[str, int]]:
    """Count planned conversations across normalized profile dimensions."""

    dimensions = {
        "by_period": "profile_period_id",
        "by_period_instance": "profile_period_instance_id",
        "by_recipe": "recipe_id",
        "by_conversation_mode": "conversation_mode",
        "by_behavior_mode": "behavior_mode",
    }
    summary: dict[str, dict[str, int]] = {}
    for output_name, field_name in dimensions.items():
        counts: dict[str, int] = {}
        for planned in plan:
            value = (
                planned.get(field_name)
                if isinstance(planned, Mapping)
                else getattr(planned, field_name)
            )
            counts[str(value)] = counts.get(str(value), 0) + 1
        summary[output_name] = dict(sorted(counts.items()))
    return summary


def _window_instances(
    profile: TimeProfile, time_window: TimeWindow
) -> list[_WindowInstance]:
    instances: list[_WindowInstance] = []
    for day_offset in range(time_window.num_synthetic_days):
        synthetic_day = time_window.start_day + timedelta(days=day_offset)
        for window in profile.windows:
            start = datetime.combine(synthetic_day, _parse_time(window.start_time))
            end = datetime.combine(synthetic_day, _parse_time(window.end_time))
            instances.append(
                _WindowInstance(
                    window=window,
                    instance_id=f"{synthetic_day.isoformat()}/{window.period_id}",
                    start=start,
                    end=end,
                )
            )
    return instances


def _allocate_instances(
    instances: Sequence[_WindowInstance], total_conversations: int
) -> list[int]:
    allocations = [1] * len(instances)
    remaining = total_conversations - len(instances)
    if remaining == 0:
        return allocations
    scaled_weights = _scale_weights(
        [instance.window.traffic_weight for instance in instances]
    )
    total_weight = math.fsum(scaled_weights)
    quotas = [remaining * (weight / total_weight) for weight in scaled_weights]
    floors = [int(quota) for quota in quotas]
    allocations = [minimum + floor for minimum, floor in zip(allocations, floors)]
    leftover = remaining - sum(floors)
    order = sorted(
        range(len(instances)),
        key=lambda index: (-(quotas[index] - floors[index]), index),
    )
    for index in order[:leftover]:
        allocations[index] += 1
    return allocations


def _weighted_recipe_id(
    active: Sequence[tuple[str, float]], rng: random.Random
) -> str:
    scaled_weights = _scale_weights([weight for _, weight in active])
    total = math.fsum(scaled_weights)
    threshold = rng.random() * total
    cumulative = 0.0
    for (recipe_id, _), weight in zip(active, scaled_weights):
        cumulative += weight
        if threshold < cumulative:
            return recipe_id
    return active[-1][0]


def _scale_weights(weights: Sequence[float]) -> list[float]:
    """Scale finite positive weights without overflowing their aggregate."""

    maximum = max(weights)
    return [weight / maximum for weight in weights]


def _parse_time(value: str) -> time:
    hours, minutes = (int(part) for part in value.split(":"))
    return time(hour=hours, minute=minutes)
