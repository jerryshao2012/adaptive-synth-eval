from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from adaptive_synth_eval.config.schemas import TimeWindow, TrafficOrchestration


@dataclass(frozen=True)
class PlannedConversation:
    conversation_id: str
    session_id: str
    persona_id: str
    scenario_id: str
    synthetic_day: object
    turn_count: int


def build_run_plan(traffic: TrafficOrchestration, window: TimeWindow) -> list[PlannedConversation]:
    rng = random.Random(traffic.random_seed)
    day_weights = _day_weights(traffic, window)
    plan = []
    for index in range(traffic.total_conversations):
        mix_item = _weighted_choice(traffic.mix, [max(item.weight, 0.0) for item in traffic.mix], rng)
        day_offset = _weighted_choice(list(range(window.num_synthetic_days)), day_weights, rng)
        turn_count = rng.randint(traffic.conversation_turns.min, traffic.conversation_turns.max)
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
