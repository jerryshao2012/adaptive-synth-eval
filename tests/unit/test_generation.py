from adaptive_synth_eval.config.schemas import FailureInjection, Persona, Scenario
from adaptive_synth_eval.generation.turns import generate_turns


def test_generate_turns_applies_failure_modes_and_metadata():
    persona = Persona(
        persona_id="P001",
        role="new_employee",
        location="Canada",
        seniority="junior",
        communication_style="confused_but_polite",
        hr_familiarity="low",
        privacy_sensitivity="medium",
    )
    scenario = Scenario(
        scenario_id="S001",
        domain="parental_leave_policy",
        intent="understand_eligibility",
        expected_retrieval_topics=["parental_leave"],
        failure_injection=FailureInjection(ambiguity=1.0, typos=1.0, missing_information=1.0),
        success_criteria={"answers_grounded_in_policy": True},
    )

    turns = generate_turns(persona, scenario, turn_count=3, seed=1)

    assert len(turns) == 3
    assert all(turn.user_message for turn in turns)
    assert {"ambiguity", "missing_information"}.issubset(set(turns[0].applied_failure_modes))
    assert "typos" in turns[0].applied_failure_modes
