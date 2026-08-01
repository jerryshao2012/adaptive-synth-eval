from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Mapping

from adaptive_synth_eval.config.schemas import (
    SimulationContract,
    TimeProfile,
    TimeWindow,
    TrafficOrchestration,
)
from adaptive_synth_eval.generation.time_profile import build_time_profile_plan


@dataclass(frozen=True)
class PlannedConversation:
    conversation_id: str
    session_id: str
    persona_id: str
    scenario_id: str
    synthetic_day: object
    turn_count: int


@dataclass(frozen=True)
class ProfiledPlannedConversation(PlannedConversation):
    sequence: int
    recipe_id: str
    synthetic_timestamp: datetime
    synthetic_slot: int
    profile_period_id: str
    profile_period_instance_id: str
    profile_period_start: datetime
    profile_period_end: datetime
    conversation_mode: str
    behavior_mode: str
    traffic_weight: float
    recipe_weights: Mapping[str, float]


def build_run_plan(
    traffic: TrafficOrchestration, window: TimeWindow
) -> list[PlannedConversation]:
    rng = random.Random(traffic.random_seed)
    day_weights = _day_weights(traffic, window)
    plan = []
    for index in range(traffic.total_conversations):
        mix_item = _weighted_choice(
            traffic.mix, [max(item.weight, 0.0) for item in traffic.mix], rng
        )
        day_offset = _weighted_choice(
            list(range(window.num_synthetic_days)), day_weights, rng
        )
        turn_count = rng.randint(
            traffic.conversation_turns.min, traffic.conversation_turns.max
        )
        conversation_id = f"conv_{index + 1:06d}"
        plan.append(
            PlannedConversation(
                conversation_id=conversation_id,
                session_id=f"sess_{index + 1:06d}",
                persona_id=mix_item.persona_id,
                scenario_id=mix_item.scenario_id,
                synthetic_day=window.start_day + timedelta(days=day_offset),
                turn_count=turn_count,
            )
        )
    return plan


def build_profiled_run_plan(
    contract: SimulationContract,
    *,
    persona_id: str | None = None,
) -> list[ProfiledPlannedConversation]:
    """Adapt the shared time-profile allocation into synth runner rows."""

    if contract.time_profile is None:
        raise ValueError("build_profiled_run_plan requires contract.time_profile")
    recipes = [
        recipe
        for recipe in contract.traffic.mix
        if persona_id is None or recipe.persona_id == persona_id
    ]
    eligible_recipe_ids = {recipe.recipe_id for recipe in recipes}
    windows = []
    for window in contract.time_profile.windows:
        recipe_weights = {
            recipe_id: weight
            for recipe_id, weight in window.recipe_weights.items()
            if recipe_id in eligible_recipe_ids and weight > 0
        }
        if not recipe_weights:
            qualifier = f" for persona {persona_id}" if persona_id else ""
            raise ValueError(
                f"time_profile period {window.period_id!r} has no eligible recipe"
                f"{qualifier}"
            )
        windows.append(replace(window, recipe_weights=recipe_weights))
    profile = TimeProfile(windows=tuple(windows))
    profiled = build_time_profile_plan(
        profile=profile,
        time_window=contract.time_window,
        total_conversations=contract.traffic.total_conversations,
        recipes=recipes,
        random_seed=contract.traffic.random_seed,
    )
    seed = 0 if contract.traffic.random_seed is None else contract.traffic.random_seed
    turn_rng = random.Random(seed)
    rows: list[ProfiledPlannedConversation] = []
    for sequence, item in enumerate(profiled, start=1):
        rows.append(
            ProfiledPlannedConversation(
                conversation_id=f"conv_{sequence:06d}",
                session_id=f"sess_{sequence:06d}",
                persona_id=item.recipe.persona_id,
                scenario_id=item.recipe.scenario_id,
                synthetic_day=item.synthetic_timestamp.date(),
                turn_count=turn_rng.randint(
                    contract.traffic.conversation_turns.min,
                    contract.traffic.conversation_turns.max,
                ),
                sequence=sequence,
                recipe_id=item.recipe_id,
                synthetic_timestamp=item.synthetic_timestamp,
                synthetic_slot=item.synthetic_slot,
                profile_period_id=item.profile_period_id,
                profile_period_instance_id=item.instance_id,
                profile_period_start=item.start,
                profile_period_end=item.end,
                conversation_mode=item.conversation_mode,
                behavior_mode=item.behavior_mode,
                traffic_weight=item.traffic_weight,
                recipe_weights=item.recipe_weights,
            )
        )
    return rows


def _day_weights(traffic: TrafficOrchestration, window: TimeWindow) -> list[float]:
    weights = [1.0 for _ in range(window.num_synthetic_days)]
    for burst in traffic.burst_patterns:
        index = burst.synthetic_day - 1
        if 0 <= index < len(weights):
            weights[index] *= burst.traffic_multiplier
    return weights


def _weighted_choice(items, weights: list[float], rng: random.Random):
    total = sum(weights)
    if total <= 0:
        return items[0]
    threshold = rng.random() * total
    current = 0.0
    for item, weight in zip(items, weights):
        current += weight
        if current >= threshold:
            return item
    return items[-1]
