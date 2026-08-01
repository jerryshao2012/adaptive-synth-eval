"""Validation coverage for the checked-in time-profile examples."""

from __future__ import annotations

from pathlib import Path

from adaptive_synth_eval.cli import detect_mode_from_file
from adaptive_synth_eval.evaluation.modes import get_mode
from adaptive_synth_eval.unified_eval.config.contract import contract_to_dict


EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"
SYNTH_EXAMPLE = EXAMPLES / "time_profile_synth_demo.yaml"
UNIFIED_EXAMPLE = EXAMPLES / "time_profile_unified_demo.yaml"
AGENT_SKILLS_EXAMPLE = EXAMPLES / "unified_agent_skills_time_profile_demo.yaml"


def _load_through_public_detection(path: Path):
    mode_name = detect_mode_from_file(str(path))
    return mode_name, get_mode(mode_name).load_contract(path)


def test_synth_time_profile_example_loads_with_ordered_distinct_recipes():
    mode_name, contract = _load_through_public_detection(SYNTH_EXAMPLE)

    assert mode_name == "synth"
    assert contract.simulation_suite.run_mode == "synthetic_chat_history_generation"
    assert contract.traffic.total_conversations == 8
    assert contract.time_profile is not None
    assert [window.period_id for window in contract.time_profile.windows] == [
        "regular_hours",
        "afternoon_rush",
    ]
    assert [window.behavior_mode for window in contract.time_profile.windows] == [
        "default",
        "stressed",
    ]
    assert [window.conversation_mode for window in contract.time_profile.windows] == [
        "routine_support",
        "urgent_escalation",
    ]
    assert contract.time_profile.windows[0].recipe_weights == {"regular_help": 1.0}
    assert contract.time_profile.windows[1].recipe_weights == {"rush_escalation": 1.0}

    recipes = {item.recipe_id: item for item in contract.traffic.mix}
    assert (recipes["regular_help"].persona_id, recipes["regular_help"].scenario_id) == (
        "PROFILE_SYNTH_EMPLOYEE",
        "PROFILE_SYNTH_POLICY",
    )
    assert (
        recipes["rush_escalation"].persona_id,
        recipes["rush_escalation"].scenario_id,
    ) == ("PROFILE_SYNTH_MANAGER", "PROFILE_SYNTH_URGENT")


def test_unified_time_profile_example_loads_as_canonical_v3_with_toxic_phase():
    mode_name, contract = _load_through_public_detection(UNIFIED_EXAMPLE)

    assert mode_name == "unified"
    assert contract.suite.run_mode == "unified"
    assert contract.eval_plan.total_conversations == 8
    assert contract.time_profile is not None
    assert [window.period_id for window in contract.time_profile.windows] == [
        "regular_hours",
        "toxicity_drill",
    ]
    assert [window.behavior_mode for window in contract.time_profile.windows] == [
        "default",
        "toxic",
    ]
    assert [window.conversation_mode for window in contract.time_profile.windows] == [
        "routine_support",
        "adversarial_pressure",
    ]
    assert contract.time_profile.windows[0].recipe_weights == {"regular_benefits": 1.0}
    assert contract.time_profile.windows[1].recipe_weights == {"toxic_pressure": 1.0}

    recipes = {entry.recipe_id: entry for entry in contract.eval_plan.entries}
    assert (
        recipes["regular_benefits"].persona_id,
        recipes["regular_benefits"].synth_scenario_id,
        recipes["regular_benefits"].adversarial_scenario_id,
    ) == (
        "PROFILE_UNIFIED_EMPLOYEE",
        "PROFILE_UNIFIED_BENEFITS",
        "PROFILE_UNIFIED_BOUNDARY",
    )
    toxic = recipes["toxic_pressure"]
    assert (toxic.persona_id, toxic.synth_scenario_id, toxic.adversarial_scenario_id) == (
        "PROFILE_UNIFIED_MANAGER",
        "PROFILE_UNIFIED_URGENT",
        "PROFILE_UNIFIED_TOXICITY",
    )
    assert toxic.schedule.mode == "bernoulli"
    assert toxic.schedule.p_synth == 0.1
    assert contract_to_dict(contract)["schema_version"] == 3


def test_agent_skills_time_profile_example_has_one_day_escalating_recipe_phases():
    mode_name, contract = _load_through_public_detection(AGENT_SKILLS_EXAMPLE)

    assert mode_name == "unified"
    assert contract_to_dict(contract)["schema_version"] == 3
    assert contract.attack_skills.enabled is True
    assert contract.attack_skills.include == ()
    assert contract.attack_skills.allowed_tools == (
        "read_skill_resource",
        "search_skill_resources",
        "inspect_target_capabilities",
        "query_attack_memory",
        "transform_payload",
    )
    assert contract.attack_skills.max_tool_calls_per_turn == 3
    assert contract.time_window.num_synthetic_days == 1
    assert contract.eval_plan.total_conversations == 12
    assert contract.eval_plan.total_conversations >= 3

    assert contract.time_profile is not None
    windows = contract.time_profile.windows
    assert [window.period_id for window in windows] == [
        "morning_regular",
        "midday_busy",
        "afternoon_toxicity_drill",
    ]
    assert [window.start_time for window in windows] == ["09:00", "12:00", "15:00"]
    assert [window.behavior_mode for window in windows] == [
        "default",
        "stressed",
        "toxic",
    ]
    assert [window.conversation_mode for window in windows] == [
        "context_building",
        "busy_hour_support",
        "adversarial_pressure",
    ]
    assert windows[1].traffic_weight > windows[0].traffic_weight
    assert windows[2].traffic_weight >= windows[1].traffic_weight

    recipes = {entry.recipe_id: entry for entry in contract.eval_plan.entries}
    assert None not in recipes
    assert len(recipes) == len(contract.eval_plan.entries) == 6
    assert set(recipes) == {
        "new_employee_benefits_pii",
        "new_employee_leave_hijack",
        "manager_benefits_toxicity",
        "manager_leave_hijack",
        "contractor_benefits_injection",
        "contractor_leave_hijack",
    }
    referenced_recipes = {
        recipe_id
        for window in windows
        for recipe_id, weight in window.recipe_weights.items()
        if weight > 0
    }
    assert referenced_recipes == set(recipes)

    morning_active = {
        recipe_id
        for recipe_id, weight in windows[0].recipe_weights.items()
        if weight > 0
    }
    assert morning_active == {
        "new_employee_benefits_pii",
        "new_employee_leave_hijack",
        "contractor_benefits_injection",
    }

    afternoon_active = {
        recipe_id
        for recipe_id, weight in windows[2].recipe_weights.items()
        if weight > 0
    }
    toxicity_recipes = [
        recipes[recipe_id]
        for recipe_id in afternoon_active
        if recipes[recipe_id].adversarial_scenario_id == "DEMO_S3_TOXIC"
    ]
    assert len(toxicity_recipes) == 1
    assert toxicity_recipes[0].schedule.mode == "bernoulli"
    assert toxicity_recipes[0].schedule.p_synth <= 0.2
