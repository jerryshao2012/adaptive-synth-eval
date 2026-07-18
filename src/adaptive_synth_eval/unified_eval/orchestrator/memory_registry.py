"""Run-scoped routing for shared, per-persona, or disabled attack memory."""
from __future__ import annotations

from adaptive_synth_eval.adversarial_response_engine.core.models import (
    AttackMemory,
    SessionState,
)


class AttackMemoryRegistry:
    def __init__(
            self,
            *,
            mode: str,
            max_entries: int,
            shared_memory: AttackMemory | None = None,
    ) -> None:
        if mode not in {"shared", "per_persona", "none"}:
            raise ValueError(f"Unsupported attack-memory mode: {mode!r}")
        self.mode = mode
        self.max_entries = max_entries
        self._shared = (
            shared_memory or AttackMemory(max_entries=max_entries)
            if mode == "shared" else None
        )
        self._per_persona: dict[str, AttackMemory] = {}

    def for_persona(self, persona_id: str) -> AttackMemory | None:
        if self.mode == "none":
            return None
        if self.mode == "shared":
            return self._shared
        memory = self._per_persona.get(persona_id)
        if memory is None:
            memory = AttackMemory(max_entries=self.max_entries)
            self._per_persona[persona_id] = memory
        return memory

    def commit(self, persona_id: str, session: SessionState | None) -> bool:
        memory = self.for_persona(persona_id)
        if memory is None or session is None:
            return False
        return memory.record_session(session)

    def to_dict(self) -> dict:
        if self.mode == "shared":
            return {"mode": self.mode, **self._shared.to_dict()}
        if self.mode == "per_persona":
            return {
                "mode": self.mode,
                "max_entries": self.max_entries,
                "personas": {
                    persona_id: memory.to_dict()
                    for persona_id, memory in sorted(self._per_persona.items())
                },
            }
        return {"mode": self.mode, "max_entries": self.max_entries, "entries": []}

    @classmethod
    def from_dict(cls, payload: dict) -> "AttackMemoryRegistry":
        mode = str(payload.get("mode", "shared"))
        max_entries = int(payload.get("max_entries", 50) or 50)
        if mode == "shared":
            shared = AttackMemory.from_dict(payload, max_entries=max_entries)
            return cls(mode=mode, max_entries=max_entries, shared_memory=shared)
        registry = cls(mode=mode, max_entries=max_entries)
        if mode == "per_persona":
            for persona_id, raw in (payload.get("personas") or {}).items():
                if isinstance(raw, dict):
                    registry._per_persona[str(persona_id)] = AttackMemory.from_dict(
                        raw, max_entries=max_entries
                    )
        return registry
