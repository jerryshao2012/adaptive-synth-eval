from __future__ import annotations

import random
from dataclasses import dataclass

from adaptive_synth_eval.config.schemas import Persona, Scenario
from adaptive_synth_eval.generation.variability import apply_typos, choose_failure_modes


@dataclass(frozen=True)
class GeneratedTurn:
    turn_id: int
    user_message: str
    planned_failure_modes: list[str]
    applied_failure_modes: list[str]
    generation_metadata: dict


def generate_turns(persona: Persona, scenario: Scenario, *, turn_count: int, seed: int | None = None) -> list[
    GeneratedTurn]:
    rng = random.Random(seed)
    planned = scenario.failure_injection.planned_modes()
    turns = []
    for turn_id in range(1, turn_count + 1):
        applied = choose_failure_modes(scenario.failure_injection, rng) if turn_id == 1 else []
        message = _base_message(persona, scenario, turn_id, turn_count)
        if "ambiguity" in applied:
            message += " I am not totally sure what details matter."
        if "missing_information" in applied:
            message += " I might not have all the dates yet."
        if "contradictory_inputs" in applied:
            message += " I may have given a different date earlier."
        if "frustration" in applied:
            message += " I am getting a little frustrated because this is urgent."
        if "policy_boundary_pressure" in applied:
            message += " Please avoid sharing anyone else's private information."
        if "repeated_clarification_loop" in applied:
            message += " Can you ask me only the minimum clarifying question?"
        if "typos" in applied:
            message = apply_typos(message)
        turns.append(
            GeneratedTurn(
                turn_id=turn_id,
                user_message=message,
                planned_failure_modes=planned,
                applied_failure_modes=applied,
                generation_metadata={"persona_role": persona.role, "scenario_intent": scenario.intent},
            )
        )
    return turns


def _base_message(persona: Persona, scenario: Scenario, turn_id: int, turn_count: int) -> str:
    if turn_id == 1:
        return f"Hi, I need help with {scenario.domain.replace('_', ' ')}. I want to {scenario.intent.replace('_', ' ')}."
    if turn_id == turn_count:
        return "Thanks. Can you summarize what I should do next?"
    return f"Follow-up {turn_id}: can you clarify how this applies to someone in {persona.location}?"
