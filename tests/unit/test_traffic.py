from datetime import date

from adaptive_synth_eval.config.schemas import BurstPattern, ConversationTurns, MixItem, TimeWindow, \
    TrafficOrchestration
from adaptive_synth_eval.generation.traffic import build_run_plan


def test_build_run_plan_is_deterministic_and_respects_total():
    traffic = TrafficOrchestration(
        total_conversations=5,
        conversation_turns=ConversationTurns(min=3, max=4),
        mix=[
            MixItem(persona_id="P001", scenario_id="S001", weight=0.7),
            MixItem(persona_id="P002", scenario_id="S002", weight=0.3),
        ],
        random_seed=123,
    )
    window = TimeWindow(start_day=date(2026, 5, 1), num_synthetic_days=2, compressed_runtime_minutes=60)

    first = build_run_plan(traffic, window)
    second = build_run_plan(traffic, window)

    assert first == second
    assert len(first) == 5
    assert all(3 <= item.turn_count <= 4 for item in first)


def test_build_run_plan_applies_burst_pattern_to_matching_day():
    traffic = TrafficOrchestration(
        total_conversations=10,
        conversation_turns=ConversationTurns(min=3, max=3),
        mix=[MixItem(persona_id="P001", scenario_id="benefits_case", weight=1.0)],
        burst_patterns=[
            BurstPattern(
                name="open_enrollment",
                synthetic_day=2,
                traffic_multiplier=4.0,
                scenario_filter=["benefits"],
            )
        ],
        random_seed=5,
    )
    window = TimeWindow(start_day=date(2026, 5, 1), num_synthetic_days=3, compressed_runtime_minutes=60)

    plan = build_run_plan(traffic, window)
    day_counts = {}
    for item in plan:
        day_counts[item.synthetic_day.isoformat()] = day_counts.get(item.synthetic_day.isoformat(), 0) + 1

    assert day_counts["2026-05-02"] > day_counts["2026-05-01"]
