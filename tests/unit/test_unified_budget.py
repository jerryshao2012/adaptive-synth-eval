from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from adaptive_synth_eval.adversarial_response_engine.core.token_budget import (
    TokenBudgetManager,
    TokenUsage,
)
from adaptive_synth_eval.adversarial_response_engine.providers.llm_client import LLMClient
from adaptive_synth_eval.unified_eval.providers.budget_meter import BudgetMeter


def test_turn_reservations_are_atomic_transient_and_released():
    budget = TokenBudgetManager(max_total_tokens=1_500)

    assert budget.try_reserve(1_000) is True
    assert budget.try_reserve(1_000) is False
    assert budget.reserved_tokens == 1_000
    assert "reserved_tokens" not in budget.snapshot()

    budget.add(TokenUsage(prompt_tokens=400, completion_tokens=200))
    budget.release_reservation(1_000)

    assert budget.reserved_tokens == 0
    assert budget.used_total_tokens == 600
    assert budget.remaining_tokens == 900


def test_owned_reservations_can_be_cleaned_up_after_conversation_failure():
    budget = TokenBudgetManager(max_total_tokens=5_000)
    assert budget.try_reserve_for("conv_1:1", 1_000) is True
    assert budget.try_reserve_for("conv_1:2", 1_000) is True
    assert budget.try_reserve_for("conv_2:1", 1_000) is True

    budget.release_reservations_for_prefix("conv_1:")

    assert budget.reserved_tokens == 1_000
    budget.release_reservation_for("conv_2:1")
    assert budget.reserved_tokens == 0


def test_budget_updates_are_thread_safe():
    budget = TokenBudgetManager(max_total_tokens=100_000)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: budget.add(TokenUsage(1, 1)), range(5_000)))

    assert budget.used_prompt_tokens == 5_000
    assert budget.used_completion_tokens == 5_000


def test_budget_meter_snapshot_restores_component_and_global_usage():
    budget = TokenBudgetManager(max_total_tokens=10_000)
    meter = BudgetMeter(budget=budget)
    meter.register("judge", "mock")
    meter.record("judge", 12, 4)

    snapshot = meter.snapshot()
    restored = BudgetMeter.from_snapshot(snapshot, max_total_tokens=10_000)

    assert restored.budget.used_prompt_tokens == 12
    assert restored.budget.used_completion_tokens == 4
    assert restored.components["judge"].calls == 1
    assert restored.components["judge"].total_tokens == 16


def test_are_usage_callback_observes_globally_charged_usage():
    budget = TokenBudgetManager(max_total_tokens=1_000)
    observed: list[int] = []
    client = LLMClient(
        lambda system, user: {
            "content": "{}",
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
        budget,
        on_usage=lambda prompt, completion: observed.append(budget.used_total_tokens),
    )

    client.complete_json("system", "user")

    assert observed == [5]
