"""Actor-owned durable persona memory for concurrent unified conversations."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from adaptive_synth_eval.config.schemas import Persona
from adaptive_synth_eval.generation.turns import PersonaMarkdownMemory


class PersonaMemoryConflictError(RuntimeError):
    """A conversation attempted to commit a different payload twice."""


@dataclass(frozen=True)
class PersonaMemorySnapshot:
    demographics: Mapping[str, Any]
    preferences: Mapping[str, Any]
    settings: Mapping[str, Any]
    summary_notes: tuple[str, ...]
    long_term_recall: tuple[str, ...]

    def to_memory(self, persona_id: str) -> PersonaMarkdownMemory:
        memory = PersonaMarkdownMemory(persona_id)
        memory.demographics.update(self.demographics)
        memory.preferences.update(self.preferences)
        memory.settings.update(self.settings)
        memory.summary_notes.extend(self.summary_notes)
        memory.long_term_recall.extend(self.long_term_recall)
        return memory


@dataclass(frozen=True)
class PersonaMemoryDelta:
    demographics: Mapping[str, Any] = field(default_factory=dict)
    preferences: Mapping[str, Any] = field(default_factory=dict)
    settings: Mapping[str, Any] = field(default_factory=dict)
    summary_notes: tuple[str, ...] = ()
    long_term_recall: tuple[str, ...] = ()

    @classmethod
    def between(
        cls,
        before: PersonaMemorySnapshot,
        after: PersonaMarkdownMemory,
    ) -> "PersonaMemoryDelta":
        def changed(
            original: Mapping[str, Any], current: Mapping[str, Any]
        ) -> dict[str, Any]:
            return {
                key: value
                for key, value in current.items()
                if key not in original or original[key] != value
            }

        def additions(original: tuple[str, ...], current: list[str]) -> tuple[str, ...]:
            remaining = Counter(original)
            added = []
            for item in current:
                if remaining[item] > 0:
                    remaining[item] -= 1
                else:
                    added.append(item)
            return tuple(added)

        return cls(
            demographics=changed(before.demographics, after.demographics),
            preferences=changed(before.preferences, after.preferences),
            settings=changed(before.settings, after.settings),
            summary_notes=additions(before.summary_notes, after.summary_notes),
            long_term_recall=additions(before.long_term_recall, after.long_term_recall),
        )

    def normalized(self) -> "PersonaMemoryDelta":
        return PersonaMemoryDelta(
            demographics=dict(self.demographics),
            preferences=dict(self.preferences),
            settings=dict(self.settings),
            summary_notes=tuple(str(item) for item in self.summary_notes),
            long_term_recall=tuple(str(item) for item in self.long_term_recall),
        )


@dataclass(frozen=True)
class _Commit:
    conversation_id: str
    sequence: int
    delta: PersonaMemoryDelta
    future: asyncio.Future[None]


@dataclass(frozen=True)
class _Snapshot:
    future: asyncio.Future[PersonaMemorySnapshot]


@dataclass(frozen=True)
class _Close:
    future: asyncio.Future[None]


class PersonaMemoryActor:
    """Single owner of a persona's durable memory and persistence lifecycle."""

    STATE_VERSION = 1
    MAX_SUMMARY_NOTES = 10
    MAX_LONG_TERM_RECALL = 20

    def __init__(self, *, persona: Persona, markdown_path: Path):
        self.persona = persona
        self.markdown_path = Path(markdown_path)
        self.state_path = self.markdown_path.with_suffix(".json")
        self._queue: asyncio.Queue[_Commit | _Snapshot | _Close] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._base: dict[str, Any] = {}
        self._updates: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        if self._task is not None:
            return
        await asyncio.to_thread(self._load)
        await asyncio.to_thread(self._persist)
        self._task = asyncio.create_task(
            self._run(), name=f"persona-memory-{self.persona.persona_id}"
        )

    async def snapshot(self) -> PersonaMemorySnapshot:
        self._require_started()
        future = asyncio.get_running_loop().create_future()
        await self._queue.put(_Snapshot(future=future))
        return await future

    async def commit(
        self,
        conversation_id: str,
        sequence: int,
        delta: PersonaMemoryDelta,
    ) -> None:
        self._require_started()
        future = asyncio.get_running_loop().create_future()
        await self._queue.put(
            _Commit(
                conversation_id=str(conversation_id),
                sequence=int(sequence),
                delta=delta.normalized(),
                future=future,
            )
        )
        await future

    async def close(self) -> None:
        if self._task is None:
            return
        future = asyncio.get_running_loop().create_future()
        await self._queue.put(_Close(future=future))
        await future
        await self._task
        self._task = None

    def _require_started(self) -> None:
        if self._task is None:
            raise RuntimeError("PersonaMemoryActor.start() must be awaited first")

    async def _run(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                if isinstance(message, _Snapshot):
                    message.future.set_result(self._snapshot())
                elif isinstance(message, _Commit):
                    await self._commit(message)
                    message.future.set_result(None)
                else:
                    message.future.set_result(None)
                    return
            except Exception as exc:  # noqa: BLE001 - propagate through actor reply
                if not message.future.done():
                    message.future.set_exception(exc)
            finally:
                self._queue.task_done()

    async def _commit(self, message: _Commit) -> None:
        payload = {
            "sequence": message.sequence,
            "delta": self._delta_to_dict(message.delta),
        }
        current = self._updates.get(message.conversation_id)
        if current is not None:
            if current == payload:
                return
            raise PersonaMemoryConflictError(
                f"Conflicting persona-memory commit for {message.conversation_id}"
            )

        self._updates[message.conversation_id] = payload
        try:
            await asyncio.to_thread(self._persist)
        except Exception:
            self._updates.pop(message.conversation_id, None)
            try:
                # The JSON source of truth is written before the Markdown view.
                # If rendering the view fails, durably restore the prior JSON
                # state so a later commit cannot accidentally preserve a delta
                # whose acknowledgement failed.
                await asyncio.to_thread(self._persist)
            except Exception:
                pass
            raise

    def _snapshot(self) -> PersonaMemorySnapshot:
        merged = self._merged()
        return PersonaMemorySnapshot(
            demographics=MappingProxyType(dict(merged["demographics"])),
            preferences=MappingProxyType(dict(merged["preferences"])),
            settings=MappingProxyType(dict(merged["settings"])),
            summary_notes=tuple(merged["summary_notes"]),
            long_term_recall=tuple(merged["long_term_recall"]),
        )

    def _merged(self) -> dict[str, Any]:
        merged = {
            "demographics": dict(self._base.get("demographics") or {}),
            "preferences": dict(self._base.get("preferences") or {}),
            "settings": dict(self._base.get("settings") or {}),
            "summary_notes": list(self._base.get("summary_notes") or []),
            "long_term_recall": list(self._base.get("long_term_recall") or []),
        }
        for _, payload in self._ordered_updates():
            delta = payload["delta"]
            for section in ("demographics", "preferences", "settings"):
                merged[section].update(delta.get(section) or {})
            merged["summary_notes"].extend(delta.get("summary_notes") or [])
            merged["long_term_recall"].extend(delta.get("long_term_recall") or [])
        merged["summary_notes"] = merged["summary_notes"][-self.MAX_SUMMARY_NOTES :]
        merged["long_term_recall"] = merged["long_term_recall"][
            -self.MAX_LONG_TERM_RECALL :
        ]
        return merged

    def _ordered_updates(self) -> list[tuple[str, dict[str, Any]]]:
        return sorted(
            self._updates.items(),
            key=lambda item: (int(item[1]["sequence"]), item[0]),
        )

    def _load(self) -> None:
        if self.state_path.exists():
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if int(payload.get("version", 0)) != self.STATE_VERSION:
                raise ValueError(
                    f"Unsupported persona-memory state version: {payload.get('version')}"
                )
            if str(payload.get("persona_id")) != self.persona.persona_id:
                raise ValueError("Persona-memory state belongs to a different persona")
            self._base = self._normalize_memory_dict(payload.get("base") or {})
            self._updates = {
                str(conversation_id): {
                    "sequence": int(raw["sequence"]),
                    "delta": self._normalize_memory_dict(raw.get("delta") or {}),
                }
                for conversation_id, raw in (payload.get("updates") or {}).items()
            }
            return

        if self.markdown_path.exists():
            memory = PersonaMarkdownMemory.load_from_file(
                self.markdown_path, self.persona.persona_id
            )
            self._base = self._memory_to_dict(memory)
        else:
            self._base = {
                "demographics": {
                    "role": self.persona.role,
                    "location": self.persona.location,
                    "seniority": self.persona.seniority,
                    "style": self.persona.communication_style,
                    "hr_familiarity": self.persona.hr_familiarity,
                    "privacy_sensitivity": self.persona.privacy_sensitivity,
                },
                "preferences": {},
                "settings": {},
                "summary_notes": [],
                "long_term_recall": [],
            }
        self._updates = {}

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        ordered_updates = {
            conversation_id: payload
            for conversation_id, payload in self._ordered_updates()
        }
        state = {
            "version": self.STATE_VERSION,
            "persona_id": self.persona.persona_id,
            "base": self._base,
            "updates": ordered_updates,
        }
        self._atomic_write(
            self.state_path,
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        )

        merged = self._merged()
        memory = PersonaMarkdownMemory(self.persona.persona_id)
        memory.demographics.update(merged["demographics"])
        memory.preferences.update(merged["preferences"])
        memory.settings.update(merged["settings"])
        memory.summary_notes.extend(merged["summary_notes"])
        memory.long_term_recall.extend(merged["long_term_recall"])
        self._atomic_write(self.markdown_path, memory.to_markdown())

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        tmp_path = path.with_name(f"{path.name}.tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    @staticmethod
    def _memory_to_dict(memory: PersonaMarkdownMemory) -> dict[str, Any]:
        return {
            "demographics": dict(memory.demographics),
            "preferences": dict(memory.preferences),
            "settings": dict(memory.settings),
            "summary_notes": list(memory.summary_notes),
            "long_term_recall": list(memory.long_term_recall),
        }

    @staticmethod
    def _normalize_memory_dict(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "demographics": dict(payload.get("demographics") or {}),
            "preferences": dict(payload.get("preferences") or {}),
            "settings": dict(payload.get("settings") or {}),
            "summary_notes": list(payload.get("summary_notes") or []),
            "long_term_recall": list(payload.get("long_term_recall") or []),
        }

    @staticmethod
    def _delta_to_dict(delta: PersonaMemoryDelta) -> dict[str, Any]:
        return {
            "demographics": dict(delta.demographics),
            "preferences": dict(delta.preferences),
            "settings": dict(delta.settings),
            "summary_notes": list(delta.summary_notes),
            "long_term_recall": list(delta.long_term_recall),
        }
