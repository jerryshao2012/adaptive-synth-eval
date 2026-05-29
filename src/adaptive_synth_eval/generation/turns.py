from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adaptive_synth_eval.clients.llm import LLMClient
from adaptive_synth_eval.config.schemas import Persona, Scenario
from adaptive_synth_eval.generation.variability import apply_typos, choose_failure_modes

logger = logging.getLogger(__name__)

# Thread-safe locks per file path to prevent concurrent write/read corruption
_memory_locks = {}
_memory_locks_lock = threading.Lock()


def _get_memory_lock(path: Path) -> threading.Lock:
    path_str = str(path.absolute())
    with _memory_locks_lock:
        if path_str not in _memory_locks:
            _memory_locks[path_str] = threading.Lock()
        return _memory_locks[path_str]


class PersonaMarkdownMemory:
    """Markdown-based memory storage for a persona's context, isolated per test run."""

    def __init__(self, persona_id: str):
        self.persona_id = persona_id
        self.demographics: dict[str, Any] = {}
        self.preferences: dict[str, Any] = {}
        self.settings: dict[str, Any] = {}
        self.summary_notes: list[str] = []
        self.long_term_recall: list[str] = []
        self.recent_window: list[dict[str, str]] = []  # list of {"role": "user"/"assistant", "text": "..."}

    @classmethod
    def load_from_file(cls, path: Path, persona_id: str) -> PersonaMarkdownMemory:
        mem = cls(persona_id)
        if not path.exists():
            return mem

        lock = _get_memory_lock(path)
        with lock:
            try:
                content = path.read_text(encoding="utf-8")
                mem.parse(content)
            except Exception:
                pass
        return mem

    def parse(self, content: str) -> None:
        lines = content.splitlines()
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("# "):
                continue
            if line.startswith("## "):
                current_section = line[3:].strip().lower()
                continue

            if line.startswith("- "):
                val = line[2:].strip()
                if current_section == "demographics":
                    if ":" in val:
                        k, v = val.split(":", 1)
                        self.demographics[k.strip().lower()] = v.strip() if v.strip() != "None" else None
                elif current_section == "preferences":
                    if ":" in val:
                        k, v = val.split(":", 1)
                        self.preferences[k.strip().lower()] = v.strip() if v.strip() != "None" else None
                elif current_section == "settings":
                    if ":" in val:
                        k, v = val.split(":", 1)
                        self.settings[k.strip().lower()] = v.strip() if v.strip() != "None" else None
                elif current_section == "summary notes":
                    self.summary_notes.append(val)
                elif current_section == "long term recall":
                    self.long_term_recall.append(val)
                elif current_section == "recent window":
                    if ":" in val:
                        role, text = val.split(":", 1)
                        role_str = role.strip().lower()
                        role_normalized = "user" if "user" in role_str or "human" in role_str else "assistant"
                        self.recent_window.append({"role": role_normalized, "text": text.strip()})

    def save_to_file(self, path: Path) -> None:
        lock = _get_memory_lock(path)
        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = self.to_markdown()
            # Use a unique temp file and retry replace to tolerate transient file locks on Windows.
            tmp_path = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
            try:
                tmp_path.write_text(content, encoding="utf-8")
                for attempt in range(6):
                    try:
                        os.replace(tmp_path, path)
                        return
                    except PermissionError:
                        if attempt == 5:
                            raise
                        time.sleep(0.02 * (attempt + 1))
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

    def to_markdown(self) -> str:
        md = []
        md.append(f"# Persona Memory: {self.persona_id}\n")

        md.append("## Demographics")
        for k, v in self.demographics.items():
            md.append(f"- {k}: {v if v is not None else 'None'}")
        md.append("")

        md.append("## Preferences")
        for k, v in self.preferences.items():
            md.append(f"- {k}: {v if v is not None else 'None'}")
        md.append("")

        md.append("## Settings")
        for k, v in self.settings.items():
            md.append(f"- {k}: {v if v is not None else 'None'}")
        md.append("")

        md.append("## Summary Notes")
        for note in self.summary_notes:
            md.append(f"- {note}")
        md.append("")

        md.append("## Long Term Recall")
        for item in self.long_term_recall:
            md.append(f"- {item}")
        md.append("")

        md.append("## Recent Window")
        for turn in self.recent_window:
            role_label = "User" if turn["role"] == "user" else "Assistant"
            md.append(f"- {role_label}: {turn['text']}")
        md.append("")

        return "\n".join(md)


@dataclass(frozen=True)
class GeneratedTurn:
    turn_id: int
    user_message: str
    planned_failure_modes: list[str]
    applied_failure_modes: list[str]
    generation_metadata: dict


class UserSimulator:
    def __init__(self, persona: Persona, scenario: Scenario, turn_count: int, seed: int | None = None,
                 memory_file: Path | None = None):
        self.persona = persona
        self.scenario = scenario
        self.turn_count = turn_count
        self.rng = random.Random(seed)
        self.history: list[dict[str, str]] = []
        self.planned_failure_modes = scenario.failure_injection.planned_modes()
        # Enable LLM client if a provider is configured in environment variables
        llm_client = LLMClient(enabled=False)  # Check if provider is available
        self.llm_client = LLMClient(enabled=llm_client.model_provider is not None)
        self.memory_file = memory_file
        self.memory = None

        if self.memory_file:
            self.memory = PersonaMarkdownMemory.load_from_file(self.memory_file, persona.persona_id)
            # Sync demographics/preferences from persona if empty
            if not self.memory.demographics:
                self.memory.demographics["role"] = persona.role
                self.memory.demographics["location"] = persona.location
                self.memory.demographics["seniority"] = persona.seniority
                self.memory.demographics["style"] = persona.communication_style
                self.memory.demographics["hr_familiarity"] = persona.hr_familiarity
                self.memory.demographics["privacy_sensitivity"] = persona.privacy_sensitivity
            # Load history from memory if present
            if self.memory.recent_window:
                self.history = []
                for turn in self.memory.recent_window:
                    role_lbl = "agent" if turn["role"] == "assistant" else "user"
                    self.history.append({"role": role_lbl, "content": turn["text"]})

    def switch_persona(self, new_persona: Persona) -> None:
        """Dynamically update the active persona mid-conversation and sync its memory state."""
        self.persona = new_persona
        if self.memory_file:
            self.memory_file = self.memory_file.parent / f"{new_persona.persona_id}_memory.md"
            self.memory = PersonaMarkdownMemory.load_from_file(self.memory_file, new_persona.persona_id)
            if not self.memory.demographics:
                self.memory.demographics["role"] = new_persona.role
                self.memory.demographics["location"] = new_persona.location
                self.memory.demographics["seniority"] = new_persona.seniority
                self.memory.demographics["style"] = new_persona.communication_style
                self.memory.demographics["hr_familiarity"] = new_persona.hr_familiarity
                self.memory.demographics["privacy_sensitivity"] = new_persona.privacy_sensitivity

            # Sync recent window to current conversation history
            self.memory.recent_window = []
            for turn in self.history:
                role_lbl = "assistant" if turn["role"] == "agent" else "user"
                self.memory.recent_window.append({"role": role_lbl, "text": turn["content"]})
            self.memory.save_to_file(self.memory_file)

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
            if self.memory:
                self.memory.recent_window.append({"role": "assistant", "text": previous_bot_response})
                self._prune_history_if_needed()
                delta = self._extract_profile_delta(previous_bot_response)
                if delta:
                    for section in ("preferences", "demographics", "settings"):
                        if section in delta:
                            self.memory.demographics.update(delta[section]) if section == "demographics" else getattr(
                                self.memory, section).update(delta[section])
                if self.memory_file:
                    self.memory.save_to_file(self.memory_file)

        behavior_mode = (behavior_override or "default").strip().lower() or "default"
        prompt = self._build_prompt(turn_id, behavior_mode=behavior_mode)
        result = self.llm_client.complete(prompt)

        if result.error:
            logger.warning(
                f"⚠️  LLM FAILED FOR PERSONA SIMULATION - Using fallback message\n"
                f"   Provider: {self.llm_client.model_provider or 'none'}\n"
                f"   Error: {result.error}\n"
                f"   Persona: {self.persona.persona_id}\n"
                f"   Turn: {turn_id}\n"
                f"   Message will be templated instead of dynamically generated!"
            )
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
        if self.memory:
            self.memory.recent_window.append({"role": "user", "text": message})
            self._prune_history_if_needed()
            delta = self._extract_profile_delta(message)
            if delta:
                for section in ("preferences", "demographics", "settings"):
                    if section in delta:
                        self.memory.demographics.update(delta[section]) if section == "demographics" else getattr(
                            self.memory, section).update(delta[section])
            if self.memory_file:
                self.memory.save_to_file(self.memory_file)

        return GeneratedTurn(
            turn_id=turn_id,
            user_message=message,
            planned_failure_modes=self.planned_failure_modes,
            applied_failure_modes=applied,
            generation_metadata={"persona_role": self.persona.role, "scenario_intent": self.scenario.intent,
                                 "dynamic": result.error != "llm_disabled", "behavior_mode": behavior_mode},
        )

    async def generate_turn_async(
            self,
            turn_id: int,
            previous_bot_response: str | None = None,
            *,
            behavior_override: str | None = None,
    ) -> GeneratedTurn:
        """Async wrapper around generate_turn() for the async simulation pipeline."""
        return await asyncio.to_thread(
            self.generate_turn,
            turn_id,
            previous_bot_response,
            behavior_override=behavior_override,
        )

    def _build_prompt(self, turn_id: int, *, behavior_mode: str = "default") -> str:
        prompt = (
            f"You are a user interacting with a customer support chatbot.\n"
            f"Your Persona: Role {self.persona.role}, Location {self.persona.location}\n"
            f"Baseline communication style: {self.persona.communication_style}\n"
            f"Your Goal: {self.scenario.intent} regarding {self.scenario.domain}\n\n"
        )

        if self.memory_file:
            context_block = self._render_memory_context_block()
            if context_block:
                prompt += context_block + "\n\n"

        prompt += "Conversation History:\n"
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

    def _extract_profile_delta(self, text: str) -> dict[str, Any]:
        """Extract profile information from text using regex patterns."""
        t = text.strip()
        lower = t.lower()
        delta: dict[str, Any] = {"preferences": {}, "demographics": {}, "settings": {}}

        # Capture name variations
        name_patterns = [
            r"\b(?:my name is|my name's)\s+([a-zA-Z ]{2,40})\b",
            r"\bi'm called ([a-zA-Z ]{2,40})\b",
            r"\bcall me ([a-zA-Z ]{2,40})\b",
            r"\b(?:i am|i'm)\s+([a-zA-Z ]{2,40})\b",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, lower)
            if match:
                delta["demographics"]["name"] = match.group(1).strip().title()
                break

        # Capture age
        age_match = re.search(r"\b(?:i am|i'm)\s+(\d{1,3})\s*(?:years? old|yo)?\b", lower)
        if age_match:
            delta["demographics"]["age"] = int(age_match.group(1))

        # Capture location
        location_match = re.search(r"\bi live in ([a-zA-Z ]{2,50})\b", lower)
        if location_match:
            delta["demographics"]["location"] = location_match.group(1).strip().title()

        # Capture favorites
        fav_match = re.search(r"\bmy favorite ([a-zA-Z ]{2,20}) is ([a-zA-Z0-9 ]{1,30})\b", lower)
        if fav_match:
            key = f"favorite_{fav_match.group(1).strip().replace(' ', '_')}"
            delta["preferences"][key] = fav_match.group(2).strip()

        # Capture preferences
        prefer_match = re.search(r"\bi prefer ([^.!,;]{2,80})", lower)
        if prefer_match:
            delta["preferences"]["stated_preference"] = prefer_match.group(1).strip()

        # Capture language
        language_match = re.search(r"\b(?:speak|use) ([a-zA-Z]{2,20})\b", lower)
        if language_match and "language" in lower:
            delta["settings"]["language"] = language_match.group(1).strip()

        # Capture email
        email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", t)
        if email_match:
            delta["demographics"]["email"] = email_match.group(0)

        # Capture phone
        phone_match = re.search(r"\b(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})\b", t)
        if phone_match:
            delta["demographics"]["phone"] = phone_match.group(0)

        return delta if any(delta[key] for key in ("preferences", "demographics", "settings")) else {}

    def _score_importance(self, text: str) -> float:
        """Score turn importance from 0.0 to 1.0."""
        score = 0.5  # Base score
        lower = text.lower()

        personal_keywords = ['name', 'prefer', 'like', 'live', 'work', 'family', 'home']
        if any(kw in lower for kw in personal_keywords):
            score += 0.3

        financial_keywords = ['account', 'transfer', 'payment', 'balance', 'loan', 'mortgage', 'card']
        if any(kw in lower for kw in financial_keywords):
            score += 0.2

        action_keywords = ['decide', 'choose', 'want', 'need', 'should', 'recommend']
        if any(kw in lower for kw in action_keywords):
            score += 0.1

        return min(1.0, score)

    def _prune_history_if_needed(self) -> None:
        """Keep the recent window size within limits and evict less important turns to summary notes."""
        if len(self.history) > 10:
            if len(self.history) > 2:
                old_turns = self.history[:-2]
                min_idx = min(range(len(old_turns)), key=lambda i: self._score_importance(old_turns[i]["content"]))
                evicted_turn = self.history.pop(min_idx)

                role_label = "User" if evicted_turn["role"] == "user" else "Assistant"
                text_snippet = evicted_turn["content"].strip().replace("\n", " ")[:180]
                if len(evicted_turn["content"]) > 180:
                    text_snippet += "..."
                note = f"{role_label}: {text_snippet}"

                if self.memory:
                    self.memory.summary_notes.append(note)
                    if len(self.memory.summary_notes) > 10:
                        self.memory.summary_notes.pop(0)

                    # Keep recent_window in memory in sync with pruned self.history
                    self.memory.recent_window = []
                    for turn in self.history:
                        role_lbl = "assistant" if turn["role"] == "agent" else "user"
                        self.memory.recent_window.append({"role": role_lbl, "text": turn["content"]})

    def _render_memory_context_block(self) -> str:
        if not self.memory:
            return ""

        sections = ["YOUR PERSONAL MEMORY AND PROFILE CONTEXT:"]

        # Demographics
        demo_strs = []
        for k, v in self.memory.demographics.items():
            if v:
                demo_strs.append(f"{k.capitalize()}: {v}")
        if demo_strs:
            sections.append("Demographics:\n" + "\n".join(f"- {s}" for s in demo_strs))

        # Preferences
        pref_strs = []
        for k, v in self.memory.preferences.items():
            if v:
                pref_strs.append(f"{k.replace('_', ' ').capitalize()}: {v}")
        if pref_strs:
            sections.append("Preferences:\n" + "\n".join(f"- {s}" for s in pref_strs))

        # Settings
        setting_strs = []
        for k, v in self.memory.settings.items():
            if v:
                setting_strs.append(f"{k.capitalize()}: {v}")
        if setting_strs:
            sections.append("Settings:\n" + "\n".join(f"- {s}" for s in setting_strs))

        # Summary Notes
        if self.memory.summary_notes:
            sections.append(
                "Key points from earlier in this conversation:\n"
                + "\n".join(f"- {note}" for note in self.memory.summary_notes)
            )

        # Long Term Recall
        if self.memory.long_term_recall:
            sections.append(
                "Long-term recall:\n"
                + "\n".join(f"- {item}" for item in self.memory.long_term_recall)
            )

        if len(sections) > 1:
            return "\n\n".join(sections)
        return ""

    def save_conversation_summary_to_long_term_recall(self) -> None:
        """Summarize current conversation history and add it to Long Term Recall in memory."""
        if not self.memory or not self.history:
            return

        user_msgs = [turn["content"] for turn in self.history if turn["role"] == "user"]
        summary = f"Interacted regarding {self.scenario.domain} to {self.scenario.intent}."
        if user_msgs:
            summary += f" Key message: '{user_msgs[0]}'"

        self.memory.long_term_recall.append(summary)
        if len(self.memory.long_term_recall) > 20:
            self.memory.long_term_recall.pop(0)

        # Clear recent window for isolation
        self.memory.recent_window = []
        if self.memory_file:
            self.memory.save_to_file(self.memory_file)

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
