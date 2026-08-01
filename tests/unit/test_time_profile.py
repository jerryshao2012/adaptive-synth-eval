from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime
import json
import random
from types import SimpleNamespace

import pytest

from adaptive_synth_eval.config.contract import ContractError, contract_to_dict, parse_contract
from adaptive_synth_eval.unified_eval.config.contract import (
    contract_to_dict as unified_contract_to_dict,
)
from adaptive_synth_eval.unified_eval.config.contract import parse_unified_contract


def _profile() -> dict:
    return {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 3,
                "conversation_mode": "support",
                "recipe_weights": {"recipe-1": 1},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "17:00",
                "traffic_weight": 1,
                "conversation_mode": "support",
                "behavior_mode": "polite",
                "recipe_weights": {"recipe-2": 1},
            },
        ]
    }


def _synth_payload(build_synth_contract_payload, *, days: int = 2, total: int = 4) -> dict:
    payload = build_synth_contract_payload(
        total_conversations=total,
        num_synthetic_days=days,
        mix=[
            {
                "recipe_id": "recipe-1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            },
            {
                "recipe_id": "recipe-2",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            },
        ],
    )
    payload["time_profile"] = _profile()
    return payload


def _unified_payload(*, days: int = 2, total: int | None = 4) -> dict:
    return {
        "schema_version": 3,
        "suite": {
            "suite_id": "profile",
            "target_application": "bot",
            "run_mode": "unified",
        },
        "run": {"random_seed": 17},
        "llm": {"provider": "mock", "model": "mock"},
        "target": {"enabled": False, "mode": "api"},
        "time_window": {
            "start_day": "2026-06-01",
            "num_synthetic_days": days,
            "compressed_runtime_minutes": 5,
        },
        "time_profile": _profile(),
        "persona_pool": [
            {
                "persona_id": "P1",
                "role": "employee",
                "location": "Toronto",
                "seniority": "junior",
                "communication_style": "direct",
                "domain_familiarity": "low",
                "data_sensitivity": "medium",
            }
        ],
        "scenario_catalog": [
            {
                "scenario_id": "S1",
                "domain": "benefits",
                "intent": "ask",
                "expected_retrieval_topics": [],
                "failure_injection": {},
                "success_criteria": {},
            }
        ],
        "adversarial_scenario_catalog": [
            {
                "scenario_id": "A1",
                "scenario_type": "toxicity",
                "scenario_text": "probe",
            }
        ],
        "eval_plan": {
            "total_conversations": total,
            "conversation_turns": {"min": 2, "max": 2},
            "entries": [
                {
                    "recipe_id": "recipe-1",
                    "persona_id": "P1",
                    "synth_scenario_id": "S1",
                    "adversarial_scenario_id": "A1",
                },
                {
                    "recipe_id": "recipe-2",
                    "persona_id": "P1",
                    "synth_scenario_id": "S1",
                    "adversarial_scenario_id": "A1",
                },
            ],
        },
    }


def test_synth_profile_parses_defaults_and_round_trips(build_synth_contract_payload):
    contract = parse_contract(_synth_payload(build_synth_contract_payload))

    assert contract.time_profile is not None
    assert tuple(window.period_id for window in contract.time_profile.windows) == (
        "morning",
        "afternoon",
    )
    assert contract.time_profile.windows[0].conversation_mode == "support"
    assert contract.time_profile.windows[0].behavior_mode == "default"
    assert contract.traffic.mix[0].recipe_id == "recipe-1"
    expected = _profile()
    expected["windows"][0]["behavior_mode"] = "default"
    normalized = contract_to_dict(contract)
    assert normalized["time_profile"] == expected
    assert normalized["traffic_orchestration"]["mix"][0]["recipe_id"] == "recipe-1"


def test_unified_profile_parses_and_serializes_as_v3():
    contract = parse_unified_contract(_unified_payload())
    normalized = unified_contract_to_dict(contract)

    assert contract.time_profile is not None
    assert contract.eval_plan.entries[1].recipe_id == "recipe-2"
    assert normalized["schema_version"] == 3
    expected = _profile()
    expected["windows"][0]["behavior_mode"] = "default"
    assert normalized["time_profile"] == expected
    assert normalized["eval_plan"]["entries"][1]["recipe_id"] == "recipe-2"


@pytest.mark.parametrize("schema_version", [1, 2, 3])
def test_unified_profile_schema_accepts_versions_1_through_3(schema_version):
    payload = _unified_payload()
    payload["schema_version"] = schema_version

    assert parse_unified_contract(payload).time_profile is not None


def test_legacy_contracts_without_profile_preserve_optional_defaults(
    build_synth_contract_payload,
):
    synth = parse_contract(build_synth_contract_payload())
    unified_payload = _unified_payload(days=1, total=1)
    unified_payload.pop("time_profile")
    for entry in unified_payload["eval_plan"]["entries"]:
        entry.pop("recipe_id")
    unified_payload["eval_plan"]["entries"] = unified_payload["eval_plan"]["entries"][:1]
    unified = parse_unified_contract(unified_payload)

    assert synth.time_profile is None
    assert synth.traffic.mix[0].recipe_id is None
    assert "time_profile" not in contract_to_dict(synth)
    assert unified.time_profile is None
    assert unified.eval_plan.entries[0].recipe_id is None
    assert "time_profile" not in unified_contract_to_dict(unified)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload["time_profile"].update(windows=payload["time_profile"]["windows"][:1]), "at least 2"),
        (lambda payload: payload["time_profile"]["windows"][1].update(period_id="morning"), "unique"),
        (lambda payload: payload["time_profile"]["windows"][0].update(start_time="8:00"), "HH:MM"),
        (lambda payload: payload["time_profile"]["windows"][0].update(end_time="08:00"), "start_time"),
        (lambda payload: payload["time_profile"]["windows"][1].update(start_time="09:00"), "overlap"),
        (lambda payload: payload["time_profile"]["windows"][0].update(traffic_weight=0), "traffic_weight"),
        (lambda payload: payload["time_profile"]["windows"][0].update(conversation_mode="  "), "conversation_mode"),
        (lambda payload: payload["time_profile"]["windows"][0].update(behavior_mode="hostile"), "behavior_mode"),
        (lambda payload: payload["time_profile"]["windows"][0].update(recipe_weights={}), "recipe_weights"),
        (lambda payload: payload["time_profile"]["windows"][0].update(recipe_weights={"recipe-1": 0}), "positive"),
        (lambda payload: payload["time_profile"]["windows"][0].update(recipe_weights={"recipe-1": -1}), "negative"),
        (lambda payload: payload["traffic_orchestration"]["mix"][0].update(recipe_id=""), "recipe_id"),
        (lambda payload: payload["traffic_orchestration"]["mix"][1].update(recipe_id="recipe-1"), "unique"),
        (lambda payload: payload["time_profile"]["windows"][0].update(recipe_weights={"missing": 1}), "unknown recipe"),
        (lambda payload: payload["traffic_orchestration"].update(total_conversations=3), "at least"),
    ],
)
def test_synth_profile_validation_rejects_invalid_config(
    build_synth_contract_payload, mutate, message
):
    payload = _synth_payload(build_synth_contract_payload)
    mutate(payload)

    with pytest.raises(ContractError, match=message):
        parse_contract(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("period_id", None),
        ("period_id", 123),
        ("period_id", []),
        ("period_id", "  "),
        ("conversation_mode", None),
        ("conversation_mode", 123),
        ("conversation_mode", []),
    ],
)
def test_profile_rejects_null_and_non_string_text_fields(
    build_synth_contract_payload, field, value
):
    payload = _synth_payload(build_synth_contract_payload)
    payload["time_profile"]["windows"][0][field] = value

    with pytest.raises(ContractError, match=rf"{field} must be a non-empty string"):
        parse_contract(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["run"].update(until_budget_exhausted=True),
        lambda payload: payload["eval_plan"].pop("total_conversations"),
    ],
)
def test_unified_profile_rejects_unbounded_runs(mutate):
    payload = _unified_payload()
    mutate(payload)

    with pytest.raises(ContractError, match="finite total_conversations"):
        parse_unified_contract(payload)


@pytest.mark.parametrize("days", [0, -1])
def test_profile_rejects_non_positive_synthetic_day_count(
    build_synth_contract_payload, days
):
    payload = _synth_payload(build_synth_contract_payload, days=days, total=4)

    with pytest.raises(ContractError, match="num_synthetic_days must be greater than 0"):
        parse_contract(payload)


@pytest.mark.parametrize("recipe_id", [123, 1.5, False, "", "  "])
def test_synth_rejects_non_string_or_blank_optional_recipe_id_without_profile(
    build_synth_contract_payload, recipe_id
):
    payload = build_synth_contract_payload()
    payload["traffic_orchestration"]["mix"][0]["recipe_id"] = recipe_id

    with pytest.raises(ContractError, match="recipe_id must be a non-empty string"):
        parse_contract(payload)


@pytest.mark.parametrize("recipe_id", [123, 1.5, False, "", "  "])
def test_unified_rejects_non_string_or_blank_optional_recipe_id_without_profile(
    recipe_id,
):
    payload = _unified_payload(days=1, total=1)
    payload.pop("time_profile")
    payload["eval_plan"]["entries"] = payload["eval_plan"]["entries"][:1]
    payload["eval_plan"]["entries"][0]["recipe_id"] = recipe_id

    with pytest.raises(ContractError, match="recipe_id must be a non-empty string"):
        parse_unified_contract(payload)


def test_normalized_outputs_reject_invalid_recipe_ids_on_direct_models(
    build_synth_contract_payload,
):
    synth = parse_contract(build_synth_contract_payload())
    synth = replace(
        synth,
        traffic=replace(
            synth.traffic,
            mix=[replace(synth.traffic.mix[0], recipe_id=123)],
        ),
    )
    unified_payload = _unified_payload(days=1, total=1)
    unified_payload.pop("time_profile")
    unified_payload["eval_plan"]["entries"] = unified_payload["eval_plan"]["entries"][:1]
    unified = parse_unified_contract(unified_payload)
    unified = replace(
        unified,
        eval_plan=replace(
            unified.eval_plan,
            entries=[replace(unified.eval_plan.entries[0], recipe_id=123)],
        ),
    )

    with pytest.raises(ContractError, match="recipe_id must be a non-empty string"):
        contract_to_dict(synth)
    with pytest.raises(ContractError, match="recipe_id must be a non-empty string"):
        unified_contract_to_dict(unified)


def test_profile_plan_is_deterministic_exact_and_repeats_windows_daily(
    build_synth_contract_payload,
):
    from adaptive_synth_eval.generation.time_profile import build_time_profile_plan

    contract = parse_contract(
        _synth_payload(build_synth_contract_payload, days=2, total=12)
    )
    kwargs = {
        "profile": contract.time_profile,
        "time_window": contract.time_window,
        "total_conversations": 12,
        "recipes": contract.traffic.mix,
        "random_seed": 29,
    }

    first = build_time_profile_plan(**kwargs)
    second = build_time_profile_plan(**kwargs)

    assert first == second
    assert len(first) == 12
    assert Counter(item.instance_id for item in first) == {
        "2026-05-01/morning": 4,
        "2026-05-01/afternoon": 2,
        "2026-05-02/morning": 4,
        "2026-05-02/afternoon": 2,
    }
    assert Counter(item.profile_period_id for item in first) == {
        "morning": 8,
        "afternoon": 4,
    }


def test_profile_plan_allocates_exactly_when_finite_traffic_weights_overflow_sum(
    build_synth_contract_payload,
):
    from adaptive_synth_eval.generation.time_profile import build_time_profile_plan

    payload = _synth_payload(build_synth_contract_payload, days=1, total=10)
    for window in payload["time_profile"]["windows"]:
        window["traffic_weight"] = 1e308
    contract = parse_contract(payload)

    plan = build_time_profile_plan(
        profile=contract.time_profile,
        time_window=contract.time_window,
        total_conversations=10,
        recipes=contract.traffic.mix,
        random_seed=29,
    )

    assert len(plan) == 10
    assert Counter(item.profile_period_id for item in plan) == {
        "morning": 5,
        "afternoon": 5,
    }


def test_profile_plan_selects_recipes_when_finite_recipe_weights_overflow_sum(
    build_synth_contract_payload,
):
    from adaptive_synth_eval.generation.time_profile import build_time_profile_plan

    payload = _synth_payload(build_synth_contract_payload, days=1, total=40)
    for window in payload["time_profile"]["windows"]:
        window["recipe_weights"] = {"recipe-1": 1e308, "recipe-2": 1e308}
    contract = parse_contract(payload)

    plan = build_time_profile_plan(
        profile=contract.time_profile,
        time_window=contract.time_window,
        total_conversations=40,
        recipes=contract.traffic.mix,
        random_seed=29,
    )

    assert len(plan) == 40
    assert {item.recipe_id for item in plan} == {"recipe-1", "recipe-2"}


def test_profile_plan_filters_recipes_and_orders_slots_and_timestamps(
    build_synth_contract_payload,
):
    from adaptive_synth_eval.generation.time_profile import build_time_profile_plan

    contract = parse_contract(
        _synth_payload(build_synth_contract_payload, days=2, total=12)
    )
    plan = build_time_profile_plan(
        profile=contract.time_profile,
        time_window=contract.time_window,
        total_conversations=12,
        recipes=contract.traffic.mix,
        random_seed=29,
    )

    assert [item.synthetic_timestamp for item in plan] == sorted(
        item.synthetic_timestamp for item in plan
    )
    for item in plan:
        assert item.start < item.synthetic_timestamp < item.end
        expected_recipe = "recipe-1" if item.profile_period_id == "morning" else "recipe-2"
        assert item.recipe_id == expected_recipe
        assert item.recipe.recipe_id == expected_recipe
        assert item.conversation_mode == "support"
        expected_weight = 3 if item.profile_period_id == "morning" else 1
        assert item.traffic_weight == expected_weight
        assert dict(item.recipe_weights) == {expected_recipe: 1}
        assert json.loads(json.dumps(item.to_dict()))["recipe_weights"] == {
            expected_recipe: 1
        }
        with pytest.raises(TypeError):
            item.recipe_weights["other"] = 1
    for instance_id in {item.instance_id for item in plan}:
        instance = [item for item in plan if item.instance_id == instance_id]
        assert [item.synthetic_slot for item in instance] == list(
            range(1, len(instance) + 1)
        )


def test_profile_plan_uses_a_stable_default_seed(build_synth_contract_payload):
    from adaptive_synth_eval.generation.time_profile import build_time_profile_plan

    payload = _synth_payload(build_synth_contract_payload, days=1, total=40)
    for window in payload["time_profile"]["windows"]:
        window["recipe_weights"] = {"recipe-1": 1, "recipe-2": 1}
    contract = parse_contract(payload)
    kwargs = {
        "profile": contract.time_profile,
        "time_window": contract.time_window,
        "total_conversations": 40,
        "recipes": contract.traffic.mix,
    }

    assert build_time_profile_plan(**kwargs) == build_time_profile_plan(**kwargs)


def test_profile_models_are_frozen(build_synth_contract_payload):
    from dataclasses import FrozenInstanceError

    contract = parse_contract(_synth_payload(build_synth_contract_payload))

    with pytest.raises(FrozenInstanceError):
        contract.time_profile.windows[0].period_id = "changed"
    with pytest.raises(TypeError):
        contract.time_profile.windows[0].recipe_weights["recipe-3"] = 1


def test_directly_constructed_profile_normalizes_nested_collections_to_immutable():
    from adaptive_synth_eval.config.schemas import TimeProfile, TimeProfileWindow

    window = TimeProfileWindow(
        period_id="morning",
        start_time="08:00",
        end_time="10:00",
        traffic_weight=1,
        recipe_weights={"recipe-1": 1},
    )
    profile = TimeProfile(windows=[window])

    with pytest.raises(TypeError):
        window.recipe_weights["recipe-2"] = 1
    with pytest.raises(AttributeError):
        profile.windows.append(window)


def test_synth_runner_plan_adapts_profile_rows_with_stable_ids_and_metadata(
    build_synth_contract_payload,
):
    from adaptive_synth_eval.generation import traffic

    contract = parse_contract(
        _synth_payload(build_synth_contract_payload, days=1, total=4)
    )

    plan = traffic.build_profiled_run_plan(contract)

    assert [row.conversation_id for row in plan] == [
        "conv_000001",
        "conv_000002",
        "conv_000003",
        "conv_000004",
    ]
    assert [row.session_id for row in plan] == [
        "sess_000001",
        "sess_000002",
        "sess_000003",
        "sess_000004",
    ]
    assert [row.sequence for row in plan] == [1, 2, 3, 4]
    assert [row.recipe_id for row in plan] == [
        "recipe-1",
        "recipe-1",
        "recipe-1",
        "recipe-2",
    ]
    assert [row.synthetic_day.isoformat() for row in plan] == ["2026-05-01"] * 4
    assert all(row.turn_count == 3 for row in plan)
    assert [row.profile_period_id for row in plan] == [
        "morning",
        "morning",
        "morning",
        "afternoon",
    ]
    assert [row.profile_period_instance_id for row in plan] == [
        "2026-05-01/morning",
        "2026-05-01/morning",
        "2026-05-01/morning",
        "2026-05-01/afternoon",
    ]
    assert all(row.profile_period_start < row.synthetic_timestamp < row.profile_period_end for row in plan)
    assert plan[-1].behavior_mode == "polite"
    assert dict(plan[-1].recipe_weights) == {"recipe-2": 1.0}


def test_synth_profiled_full_plan_uses_stable_default_seed_for_turn_counts(
    build_synth_contract_payload,
):
    from adaptive_synth_eval.config.schemas import ConversationTurns
    from adaptive_synth_eval.generation.traffic import build_profiled_run_plan

    contract = parse_contract(
        _synth_payload(build_synth_contract_payload, days=2, total=12)
    )
    contract = replace(
        contract,
        traffic=replace(
            contract.traffic,
            random_seed=None,
            conversation_turns=ConversationTurns(min=3, max=8),
        ),
    )

    first = build_profiled_run_plan(contract)
    second = build_profiled_run_plan(contract)
    expected_rng = random.Random(0)

    assert first == second
    assert [row.turn_count for row in first] == [
        expected_rng.randint(3, 8) for _ in first
    ]


def test_unified_finite_plan_uses_active_profile_recipes_and_preserves_schedule():
    from adaptive_synth_eval.unified_eval.orchestrator import runner

    contract = parse_unified_contract(_unified_payload(days=1, total=4))

    plan = runner._build_plan(
        contract,
        persona_filter=None,
        scenario_filter=None,
        adversarial_filter=None,
    )

    assert [row["recipe_id"] for row in plan] == [
        "recipe-1",
        "recipe-1",
        "recipe-1",
        "recipe-2",
    ]
    assert [row["entry"] for row in plan[:3]] == [contract.eval_plan.entries[0]] * 3
    assert plan[-1]["entry"] is contract.eval_plan.entries[1]
    assert all(row["schedule"] == row["entry"].schedule for row in plan)
    assert [row["synthetic_day"].isoformat() for row in plan] == ["2026-06-01"] * 4
    assert [row["profile_period_id"] for row in plan] == [
        "morning",
        "morning",
        "morning",
        "afternoon",
    ]
    assert plan[-1]["behavior_mode"] == "polite"
    assert plan[-1]["profile_period_instance_id"] == "2026-06-01/afternoon"


def test_unified_profile_plan_respects_entry_filters():
    from adaptive_synth_eval.unified_eval.orchestrator import runner

    payload = _unified_payload(days=1, total=4)
    payload["persona_pool"].append(
        {
            **payload["persona_pool"][0],
            "persona_id": "P2",
        }
    )
    payload["eval_plan"]["entries"][1]["persona_id"] = "P2"
    contract = parse_unified_contract(payload)

    plan = runner._build_plan(
        contract,
        persona_filter="P1",
        scenario_filter=None,
        adversarial_filter=None,
    )

    assert len(plan) == 4
    assert {row["persona_id"] for row in plan} == {"P1"}
    assert {row["recipe_id"] for row in plan} == {"recipe-1"}
    assert {row["profile_period_id"] for row in plan} == {"morning"}


def test_profile_plan_serialization_and_fingerprint_are_stable():
    from adaptive_synth_eval.unified_eval.orchestrator import runner

    contract = parse_unified_contract(_unified_payload(days=1, total=4))

    def serialized():
        plan = runner._build_plan(
            contract,
            persona_filter=None,
            scenario_filter=None,
            adversarial_filter=None,
        )
        for sequence, row in enumerate(plan, 1):
            row["sequence"] = sequence
            row["conversation_id"] = f"conv_{sequence:06d}"
        return runner._serialize_plan(plan)

    first = serialized()
    second = serialized()

    assert first == second
    assert runner._fingerprint_payload(first) == runner._fingerprint_payload(second)
    assert all(
        {
            "sequence",
            "recipe_id",
            "synthetic_timestamp",
            "synthetic_slot",
            "profile_period_id",
            "profile_period_instance_id",
            "profile_period_start",
            "profile_period_end",
            "conversation_mode",
            "behavior_mode",
            "traffic_weight",
            "recipe_weights",
            "synthetic_day",
        }
        <= row.keys()
        for row in first
    )


def test_no_profile_planners_do_not_add_profile_metadata(
    build_synth_contract_payload,
):
    from adaptive_synth_eval.generation import traffic
    from adaptive_synth_eval.unified_eval.orchestrator import runner

    synth = parse_contract(build_synth_contract_payload(total_conversations=1))
    synth_plan = traffic.build_run_plan(synth.traffic, synth.time_window)
    assert set(synth_plan[0].__dict__) == {
        "conversation_id",
        "session_id",
        "persona_id",
        "scenario_id",
        "synthetic_day",
        "turn_count",
    }

    payload = _unified_payload(days=1, total=1)
    payload.pop("time_profile")
    payload["eval_plan"]["entries"] = payload["eval_plan"]["entries"][:1]
    payload["eval_plan"]["entries"][0].pop("recipe_id")
    unified = parse_unified_contract(payload)
    unified_plan = runner._build_plan(
        unified,
        persona_filter=None,
        scenario_filter=None,
        adversarial_filter=None,
    )
    assert "profile_period_id" not in unified_plan[0]


def test_profile_turn_timestamps_are_monotonic_and_stay_inside_period(
    build_synth_contract_payload,
):
    from adaptive_synth_eval.generation.time_profile import profile_turn_timestamp
    from adaptive_synth_eval.generation.traffic import build_profiled_run_plan

    contract = parse_contract(
        _synth_payload(build_synth_contract_payload, days=1, total=4)
    )
    planned = build_profiled_run_plan(contract)[0]

    timestamps = [
        profile_turn_timestamp(planned, turn_id=turn_id, turn_count=20)
        for turn_id in range(1, 21)
    ]

    assert timestamps[0] == planned.synthetic_timestamp
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == len(timestamps)
    assert timestamps[-1] <= planned.profile_period_end
    assert all(datetime.fromisoformat(value.isoformat()) == value for value in timestamps)


def test_profile_behavior_is_default_unless_live_control_explicitly_overrides():
    from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController
    from adaptive_synth_eval.generation.time_profile import resolve_behavior_override

    controller = RealtimeChatController(personas={"P1": {}}, single_persona_mode=True)
    controller.set_active_persona("P1")

    assert resolve_behavior_override("stressed", controller, "P1") == "stressed"
    controller.apply_command("style toxic")
    assert resolve_behavior_override("stressed", controller, "P1") == "toxic"


@pytest.mark.asyncio
async def test_synth_profile_execution_has_phase_barrier_and_ordered_results():
    from adaptive_synth_eval.engines import chat_history_simulation

    items = [
        SimpleNamespace(sequence=1, profile_period_instance_id="day/morning"),
        SimpleNamespace(sequence=2, profile_period_instance_id="day/morning"),
        SimpleNamespace(sequence=3, profile_period_instance_id="day/afternoon"),
    ]
    active = 0
    peak = 0
    morning_finished = 0

    async def worker(item):
        nonlocal active, peak, morning_finished
        if item.profile_period_instance_id.endswith("afternoon"):
            assert morning_finished == 2
        active += 1
        peak = max(peak, active)
        if item.sequence == 1:
            await asyncio.sleep(0.02)
        else:
            await asyncio.sleep(0)
        active -= 1
        if item.profile_period_instance_id.endswith("morning"):
            morning_finished += 1
        return item.sequence

    results = []
    async for result in chat_history_simulation._profiled_bounded_results(
        items,
        worker=worker,
        max_concurrency=2,
        can_admit=lambda: True,
    ):
        results.append(result)

    assert peak == 2
    assert results == [1, 2, 3]


@pytest.mark.asyncio
async def test_synth_profile_execution_streams_contiguous_results_before_period_finishes():
    from adaptive_synth_eval.engines import chat_history_simulation

    items = [
        SimpleNamespace(sequence=1, profile_period_instance_id="day/morning"),
        SimpleNamespace(sequence=2, profile_period_instance_id="day/morning"),
        SimpleNamespace(sequence=3, profile_period_instance_id="day/afternoon"),
    ]
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    afternoon_started = asyncio.Event()

    async def worker(item):
        if item.sequence == 1:
            return 1
        if item.sequence == 2:
            second_started.set()
            await release_second.wait()
            return 2
        afternoon_started.set()
        return 3

    results = chat_history_simulation._profiled_bounded_results(
        items,
        worker=worker,
        max_concurrency=2,
        can_admit=lambda: True,
    )
    first_result = asyncio.create_task(anext(results))
    await second_started.wait()
    await asyncio.sleep(0)
    try:
        assert first_result.done()
        assert first_result.result() == 1
        assert not afternoon_started.is_set()

        second_result = asyncio.create_task(anext(results))
        release_second.set()
        assert await second_result == 2
        assert not afternoon_started.is_set()
        assert await anext(results) == 3
        with pytest.raises(StopAsyncIteration):
            await anext(results)
    finally:
        release_second.set()
        if not first_result.done():
            await first_result
        await results.aclose()


@pytest.mark.asyncio
async def test_unified_profile_execution_has_phase_barrier_with_phase_concurrency():
    from adaptive_synth_eval.unified_eval.orchestrator import runner

    items = [
        {"sequence": 1, "profile_period_instance_id": "day/morning"},
        {"sequence": 2, "profile_period_instance_id": "day/morning"},
        {"sequence": 3, "profile_period_instance_id": "day/afternoon"},
    ]
    active = 0
    peak = 0
    morning_finished = 0

    async def worker(item):
        nonlocal active, peak, morning_finished
        if item["profile_period_instance_id"].endswith("afternoon"):
            assert morning_finished == 2
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        if item["profile_period_instance_id"].endswith("morning"):
            morning_finished += 1

    await runner._run_profiled_sliding_window(
        items,
        worker=worker,
        max_concurrency=2,
        can_admit=lambda: True,
    )

    assert peak == 2


def test_unified_profile_realtime_persona_filter_keeps_full_filtered_plan():
    from adaptive_synth_eval.unified_eval.orchestrator import runner

    contract = parse_unified_contract(_unified_payload(days=1, total=4))
    plan = runner._build_plan(
        contract,
        persona_filter="P1",
        scenario_filter=None,
        adversarial_filter=None,
    )

    ordered = runner._prepare_realtime_plan(
        plan,
        contract=contract,
        persona_filter="P1",
    )

    assert len(ordered) == 4
    assert {row["persona_id"] for row in ordered} == {"P1"}
    assert [row["profile_period_instance_id"] for row in ordered] == [
        "2026-06-01/morning",
        "2026-06-01/morning",
        "2026-06-01/morning",
        "2026-06-01/afternoon",
    ]


def test_unified_profile_realtime_round_robin_stays_inside_period_instances():
    from adaptive_synth_eval.unified_eval.orchestrator import runner

    contract = parse_unified_contract(_unified_payload(days=1, total=4))
    plan = [
        {"persona_id": "P1", "profile_period_instance_id": "day/morning", "id": 1},
        {"persona_id": "P1", "profile_period_instance_id": "day/morning", "id": 2},
        {"persona_id": "P2", "profile_period_instance_id": "day/morning", "id": 3},
        {"persona_id": "P2", "profile_period_instance_id": "day/afternoon", "id": 4},
        {"persona_id": "P1", "profile_period_instance_id": "day/afternoon", "id": 5},
    ]

    ordered = runner._prepare_realtime_plan(
        plan,
        contract=contract,
        persona_filter=None,
    )

    assert [row["profile_period_instance_id"] for row in ordered] == [
        "day/morning",
        "day/morning",
        "day/morning",
        "day/afternoon",
        "day/afternoon",
    ]
    assert [row["id"] for row in ordered] == [1, 3, 2, 5, 4]
