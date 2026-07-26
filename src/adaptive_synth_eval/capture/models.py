"""Versioned capture envelope, skeleton, trigger, and promotion records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _json_safe(value: Any) -> Any:
    """Recursively normalize dataclass values to stable JSON wire values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _wire_dict(value: Any) -> dict[str, Any]:
    """Convert a dataclass instance to a JSON-compatible mapping."""
    return _json_safe(asdict(value))


class TriggerSeverity(str, Enum):
    """Severity levels for capture triggers."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriggerSource(str, Enum):
    """Source classification for triggers."""

    AGENT_EMITTED = "agent"
    NATIVE_ROW_SIGNAL = "native"
    HEURISTIC = "heuristic"


class PromotionRole(str, Enum):
    """Role of a turn in relation to a trigger."""

    BEFORE = "before"
    TRIGGER = "trigger"
    AFTER = "after"


@dataclass(frozen=True)
class CaptureTrigger:
    """Typed trigger event that may promote wider context."""

    trigger_id: str
    """Stable, idempotent trigger identifier: <run_id>/<source>/<event_type>/<context_hash>."""

    source: TriggerSource
    """Classification: agent-emitted, native row signal, or deterministic heuristic."""

    event_type: str
    """Event category (e.g., 'error', 'latency_sla_breach', 'applied_failure_mode', 'safety_score_low')."""

    severity: TriggerSeverity
    """Severity for ordering and budgeting."""

    detector_name: str
    """Name/version of the detector that fired (e.g., 'latency_heuristic_v1', 'agent_event_parser')."""

    reason: str
    """Human-readable reason why the trigger fired."""

    timestamp: str
    """ISO 8601 timestamp when the trigger was detected."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional context, redacted of sensitive values."""

    rule_id: str | None = None
    """Stable declarative rule identifier."""

    policy_fingerprint: str | None = None
    """Fingerprint of the policy that produced this trigger."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return _wire_dict(self)


@dataclass(frozen=True)
class SkeletonRecord:
    """Compact, privacy-safe central record derived from a rich local envelope."""

    skeleton_id: str
    """Stable identifier: <run_id>/<producer_id>/<conversation_id>/<turn_id>/<event_seq>."""

    producer_id: str
    """Source producer: 'persona:<id>', 'attack:<id>', 'target:<id>', etc."""

    conversation_id: str
    """Conversation/session identifier."""

    turn_id: int
    """Turn sequence within conversation."""

    timestamp: str
    """ISO 8601 timestamp of the source record."""

    event_type: str
    """Type of record: 'chat_turn', 'persona_memory_commit', 'attack_memory_entry', etc."""

    content_digest: str
    """SHA256(first 1KB of rich payload) for cache invalidation."""

    content_size_bytes: int
    """Size of the full local-buffer payload."""

    buffer_locator: str | None
    """Path or URI to the local rich buffer (if persisted)."""

    status: str
    """Status summary (e.g., 'success', 'truncated', 'error')."""

    trigger_ids: list[str] = field(default_factory=list)
    """Triggered capture events that reference this row."""

    promoted_reason: str | None = None
    """If promoted to central store, reason (e.g., 'trigger_detected', 'context_lookback')."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Auxiliary data: lengths, scores, counts, digests, etc., without raw text."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return _wire_dict(self)


@dataclass(frozen=True)
class PromotionRecord:
    """Full or partial capture promoted from local buffer to central evaluation."""

    promotion_id: str
    """Stable identifier: <run_id>/<trigger_id>/<turn_key>/<role>."""

    trigger_id: str
    """Triggering event."""

    promoted_turn_key: tuple[str, int]
    """(conversation_id, turn_id) of the promoted row."""

    promotion_role: PromotionRole
    """before/trigger/after."""

    promoted_content_digest: str
    """SHA256 of promoted content for deduplication."""

    promoted_size_bytes: int | None = None
    """Size of promoted data, or None if ephemeral."""

    timestamp: str = field(
        default_factory=lambda: (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
    )
    """When promotion occurred."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Optional per-promotion metadata."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return _wire_dict(self)


@dataclass(frozen=True)
class CaptureEnvelope:
    """Local rich record with provenance, ready for optional skeleton extraction and promotion."""

    envelope_id: str
    """Stable idempotency key."""

    source_artifact: str
    """Origin: 'chat_history', 'persona_memory', 'attack_memory', etc."""

    producer_id: str
    """'persona:<id>', 'attack:<id>', 'target:<id>'."""

    conversation_id: str
    """Conversation/session identifier."""

    turn_id: int
    """Turn sequence or event index."""

    timestamp: str
    """ISO 8601 UTC timestamp."""

    content: dict[str, Any]
    """Full rich payload: user/bot messages, memory deltas, attack entries, metadata, etc."""

    source_version: int = 1
    """Version of the content schema."""

    def skeleton(self, buffer_locator: str | None = None) -> SkeletonRecord:
        """Extract compact skeleton for central store."""
        canonical_content = json.dumps(
            _json_safe(self.content),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        content_digest = hashlib.sha256(canonical_content).hexdigest()

        metadata = {}
        for key in ("error", "latency_ms", "applied_failure_modes", "safety_score"):
            if key in self.content:
                metadata[key] = self.content[key]

        return SkeletonRecord(
            skeleton_id=self.envelope_id,
            producer_id=self.producer_id,
            conversation_id=self.conversation_id,
            turn_id=self.turn_id,
            timestamp=self.timestamp,
            event_type=self.source_artifact,
            content_digest=content_digest,
            content_size_bytes=len(canonical_content),
            buffer_locator=buffer_locator,
            status="success",
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return _json_safe(
            {
                "envelope_id": self.envelope_id,
                "source_artifact": self.source_artifact,
                "producer_id": self.producer_id,
                "conversation_id": self.conversation_id,
                "turn_id": self.turn_id,
                "timestamp": self.timestamp,
                "content": self.content,
                "source_version": self.source_version,
            }
        )


@dataclass(frozen=True)
class CaptureManifest:
    """Metadata describing a run's capture configuration and storage."""

    run_id: str
    """Associated run identifier."""

    schema_version: int
    """Capture domain version (for migration)."""

    sink_type: str
    """'jsonl', 's3', 'database', etc."""

    sink_config: dict[str, Any]
    """Sink-specific settings (e.g., paths, credentials redacted)."""

    trigger_policy_fingerprint: str
    """SHA256 of normalized trigger policy."""

    trigger_lookback_turns: int
    """Context turns before trigger."""

    trigger_lookahead_turns: int
    """Context turns after trigger."""

    capture_budget_per_window: int
    """Deterministic budget in triggered mode."""

    created_at: str
    """ISO 8601 UTC timestamp when manifest was created."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional manifest-level metadata."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return _wire_dict(self)
