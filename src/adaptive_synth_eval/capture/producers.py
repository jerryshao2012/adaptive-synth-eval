"""Producer adapters for capture envelope emission."""

from __future__ import annotations

from typing import Any

from adaptive_synth_eval.capture.models import CaptureEnvelope
from adaptive_synth_eval.capture.sinks import CaptureCoordinator


class ChatHistoryProducerAdapter:
    """Adapter for emitting capture envelopes from chat history turns."""

    def __init__(self, coordinator: CaptureCoordinator | None = None):
        """Initialize with optional capture coordinator."""
        self.coordinator = coordinator

    def emit_chat_turn(
        self,
        conversation_id: str,
        turn_id: int,
        producer_id: str,
        content: dict[str, Any],
        timestamp: str | None = None,
    ) -> Any | None:
        """Emit a chat turn as a capture envelope.

        Args:
            conversation_id: Conversation ID.
            turn_id: Turn number in conversation.
            producer_id: Source ID (persona:P001, target:id, attack:id).
            content: Turn content dict (user_message, bot_response, error, latency_ms, etc.).
            timestamp: Optional ISO timestamp; defaults to current.
        """
        if not self.coordinator:
            return None

        from datetime import datetime, timezone

        envelope = CaptureEnvelope(
            envelope_id=f"chat-{conversation_id}-{turn_id}",
            source_artifact="chat_history",
            producer_id=producer_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            timestamp=timestamp
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            content=content,
        )

        # Buffer locally, emit skeleton to centralized sink
        return self.coordinator.emit_envelope(
            envelope,
            promote=False,
            producer_id=producer_id,
        )


class PersonaMemoryProducerAdapter:
    """Adapter for emitting capture envelopes from persona memory commits."""

    def __init__(self, coordinator: CaptureCoordinator | None = None):
        """Initialize with optional capture coordinator."""
        self.coordinator = coordinator

    def emit_memory_commit(
        self,
        conversation_id: str,
        persona_id: str,
        memory_delta: dict[str, Any],
        timestamp: str | None = None,
    ) -> None:
        """Emit a persona memory commit as a capture envelope.

        Args:
            conversation_id: Conversation ID.
            persona_id: Persona ID.
            memory_delta: Delta changes (demographics, preferences, settings, notes).
            timestamp: Optional ISO timestamp.
        """
        if not self.coordinator:
            return

        from datetime import datetime, timezone

        envelope = CaptureEnvelope(
            envelope_id=f"mem-{persona_id}-{conversation_id}",
            source_artifact="persona_memory",
            producer_id=f"persona:{persona_id}",
            conversation_id=conversation_id,
            turn_id=0,  # Memory commits are conversation-scoped, not turn-scoped
            timestamp=timestamp
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            content=memory_delta,
        )

        # Buffer locally as skeleton (memory is sensitive)
        self.coordinator.emit_envelope(
            envelope, promote=False, producer_id=f"persona:{persona_id}"
        )


class AttackMemoryProducerAdapter:
    """Adapter for emitting capture envelopes from attack memory commits."""

    def __init__(self, coordinator: CaptureCoordinator | None = None):
        """Initialize with optional capture coordinator."""
        self.coordinator = coordinator

    def emit_attack_memory_commit(
        self,
        conversation_id: str,
        persona_id: str,
        attack_session: dict[str, Any],
        timestamp: str | None = None,
    ) -> None:
        """Emit attack memory session as a capture envelope.

        Args:
            conversation_id: Conversation ID.
            persona_id: Persona ID (may be None for shared attack memory).
            attack_session: Attack session entry (strategy, effectiveness, near_miss, etc.).
            timestamp: Optional ISO timestamp.
        """
        if not self.coordinator:
            return

        from datetime import datetime, timezone

        attack_id = attack_session.get("session_id", f"attack-{conversation_id}")
        producer = f"attack:{attack_id}"

        envelope = CaptureEnvelope(
            envelope_id=f"atk-{attack_id}-{conversation_id}",
            source_artifact="attack_memory",
            producer_id=producer,
            conversation_id=conversation_id,
            turn_id=0,  # Attack session-scoped
            timestamp=timestamp
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            content=attack_session,
        )

        # Buffer locally as skeleton (attack details are sensitive)
        self.coordinator.emit_envelope(envelope, promote=False, producer_id=producer)
