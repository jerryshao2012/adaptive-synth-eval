from __future__ import annotations

import random
from dataclasses import dataclass

from adaptive_synth_eval.clients.llm import LLMClient
from adaptive_synth_eval.config.schemas import Persona, Scenario
from adaptive_synth_eval.generation.variability import apply_typos, choose_failure_modes


@dataclass(frozen=True)
class GeneratedTurn:
    turn_id: int
    user_message: str
    planned_failure_modes: list[str]
    applied_failure_modes: list[str]
    generation_metadata: dict


class UserSimulator:
    def __init__(self, persona: Persona, scenario: Scenario, turn_count: int, seed: int | None = None):
        self.persona = persona
        self.scenario = scenario
        self.turn_count = turn_count
        self.rng = random.Random(seed)
        self.history = []
        self.planned_failure_modes = scenario.failure_injection.planned_modes()
        # Enable LLM client if a provider is configured in environment variables
        llm_client = LLMClient(enabled=False)  # Check if provider is available
        self.llm_client = LLMClient(enabled=llm_client.model_provider is not None)

    def generate_turn(self, turn_id: int, previous_bot_response: str | None = None) -> GeneratedTurn:
        applied = choose_failure_modes(self.scenario.failure_injection, self.rng) if turn_id == 1 else []

        if previous_bot_response:
            self.history.append({"role": "agent", "content": previous_bot_response})

        prompt = self._build_prompt(turn_id)
        result = self.llm_client.complete(prompt)

        if result.error == "llm_disabled":
            message = self._fallback_message(turn_id)
        else:
            message = result.content

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

        self.history.append({"role": "user", "content": message})

        return GeneratedTurn(
            turn_id=turn_id,
            user_message=message,
            planned_failure_modes=self.planned_failure_modes,
            applied_failure_modes=applied,
            generation_metadata={"persona_role": self.persona.role, "scenario_intent": self.scenario.intent,
                                 "dynamic": result.error != "llm_disabled"},
        )

    def _build_prompt(self, turn_id: int) -> str:
        prompt = (
            f"You are a user interacting with a customer support chatbot.\n"
            f"Your Persona: Role {self.persona.role}, Location {self.persona.location}\n"
            f"Your Goal: {self.scenario.intent} regarding {self.scenario.domain}\n\n"
            "Conversation History:\n"
        )
        for msg in self.history:
            prompt += f"{msg['role'].capitalize()}: {msg['content']}\n"

        if turn_id == 1:
            prompt += "\nPlease provide your opening message to the agent."
        elif turn_id == self.turn_count:
            prompt += "\nThis is the final turn. Please ask the agent to summarize what you should do next."
        else:
            prompt += "\nPlease provide your next response as this user."

        return prompt

    def _fallback_message(self, turn_id: int) -> str:
        if turn_id == 1:
            return f"Hi, I need help with {self.scenario.domain.replace('_', ' ')}. I want to {self.scenario.intent.replace('_', ' ')}."
        if turn_id == self.turn_count:
            return "Thanks. Can you summarize what I should do next?"
        return f"Follow-up {turn_id}: can you clarify how this applies to someone in {self.persona.location}?"


def generate_turns(persona: Persona, scenario: Scenario, turn_count: int, seed: int | None = None) -> list[GeneratedTurn]:
    """Convenience function to generate all turns for a conversation.
    
    Args:
        persona: The user persona
        scenario: The conversation scenario
        turn_count: Number of turns to generate
        seed: Random seed for reproducibility
    
    Returns:
        List of GeneratedTurn objects
    """
    simulator = UserSimulator(persona=persona, scenario=scenario, turn_count=turn_count, seed=seed)
    turns = []
    previous_bot_response = None
    
    for turn_id in range(1, turn_count + 1):
        turn = simulator.generate_turn(turn_id=turn_id, previous_bot_response=previous_bot_response)
        turns.append(turn)
        # Simulate a generic bot response for context in next turn
        previous_bot_response = f"I understand you're asking about turn {turn_id}."
    
    return turns
