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

    def generate_turn(
            self,
            turn_id: int,
            previous_bot_response: str | None = None,
            *,
            behavior_override: str | None = None,
    ) -> GeneratedTurn:
        applied = choose_failure_modes(self.scenario.failure_injection, self.rng) if turn_id == 1 else []

        if previous_bot_response:
            self.history.append({"role": "agent", "content": previous_bot_response})

        behavior_mode = (behavior_override or "default").strip().lower() or "default"
        prompt = self._build_prompt(turn_id, behavior_mode=behavior_mode)
        result = self.llm_client.complete(prompt)

        if result.error == "llm_disabled":
            message = self._fallback_message(turn_id, behavior_mode=behavior_mode)
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
                                 "dynamic": result.error != "llm_disabled", "behavior_mode": behavior_mode},
        )

    def _build_prompt(self, turn_id: int, *, behavior_mode: str = "default") -> str:
        prompt = (
            f"You are a user interacting with a customer support chatbot.\n"
            f"Your Persona: Role {self.persona.role}, Location {self.persona.location}\n"
            f"Baseline communication style: {self.persona.communication_style}\n"
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

        style_instruction = self._style_instruction(behavior_mode)
        if style_instruction:
            prompt += f"\n\nRuntime behavior mode: {behavior_mode}. {style_instruction}"

        return prompt

    def _fallback_message(self, turn_id: int, *, behavior_mode: str = "default") -> str:
        if turn_id == 1:
            base = (
                f"Hi, I need help with {self.scenario.domain.replace('_', ' ')}. "
                f"I want to {self.scenario.intent.replace('_', ' ')}."
            )
            return self._apply_behavior_to_fallback(base, behavior_mode=behavior_mode)
        if turn_id == self.turn_count:
            return self._apply_behavior_to_fallback(
                "Thanks. Can you summarize what I should do next?",
                behavior_mode=behavior_mode,
            )
        base = f"Follow-up {turn_id}: can you clarify how this applies to someone in {self.persona.location}?"
        return self._apply_behavior_to_fallback(base, behavior_mode=behavior_mode)

    @staticmethod
    def _style_instruction(behavior_mode: str) -> str:
        if behavior_mode == "aggressive":
            return "Be assertive, direct, and urgent while staying non-abusive."
        if behavior_mode == "polite":
            return "Use courteous and appreciative language."
        if behavior_mode == "concise":
            return "Keep the message brief and to the point."
        if behavior_mode == "confused":
            return "Sound uncertain and ask for clarification on key terms."
        if behavior_mode == "anxious":
            return "Convey concern and urgency without hostility."
        return ""

    def _apply_behavior_to_fallback(self, message: str, *, behavior_mode: str) -> str:
        if behavior_mode == "aggressive":
            return f"I need a clear answer now. {message}"
        if behavior_mode == "polite":
            return f"Please and thank you for your help. {message}"
        if behavior_mode == "concise":
            words = message.split()
            return " ".join(words[: min(10, len(words))])
        if behavior_mode == "confused":
            return f"I might be misunderstanding this. {message}"
        if behavior_mode == "anxious":
            return f"I am really worried about this timeline. {message}"
        return message


def generate_turns(persona: Persona, scenario: Scenario, turn_count: int, seed: int | None = None) -> list[
    GeneratedTurn]:
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
