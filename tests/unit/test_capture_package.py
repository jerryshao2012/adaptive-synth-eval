"""Regression tests for the public capture package."""

from __future__ import annotations

import hashlib
import json


def test_capture_package_exports_producer_adapters() -> None:
    import adaptive_synth_eval.capture as capture

    assert capture.ChatHistoryProducerAdapter
    assert capture.PersonaMemoryProducerAdapter
    assert capture.AttackMemoryProducerAdapter


def test_envelope_skeleton_uses_full_canonical_utf8_payload() -> None:
    from adaptive_synth_eval.capture.models import CaptureEnvelope

    content = {
        "z": "é" * 700,
        "a": {"severity": "high", "values": [3, 2, 1]},
    }
    envelope = CaptureEnvelope(
        envelope_id="env-1",
        source_artifact="chat_history",
        producer_id="target:default",
        conversation_id="conversation-1",
        turn_id=1,
        timestamp="2026-07-26T00:00:00Z",
        content=content,
    )

    canonical = json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    skeleton = envelope.skeleton(buffer_locator="capture/local/target.jsonl#env-1")

    assert skeleton.content_digest == hashlib.sha256(canonical).hexdigest()
    assert skeleton.content_size_bytes == len(canonical)
    assert skeleton.buffer_locator == "capture/local/target.jsonl#env-1"


def test_wire_serialization_normalizes_enums_and_tuples() -> None:
    from adaptive_synth_eval.capture.models import (
        CaptureTrigger,
        PromotionRecord,
        PromotionRole,
        TriggerSeverity,
        TriggerSource,
    )

    trigger = CaptureTrigger(
        trigger_id="trigger-1",
        source=TriggerSource.NATIVE_ROW_SIGNAL,
        event_type="error",
        severity=TriggerSeverity.HIGH,
        detector_name="error-v1",
        reason="error",
        timestamp="2026-07-26T00:00:00Z",
        metadata={"nested": {"severity": TriggerSeverity.LOW}},
    )
    promotion = PromotionRecord(
        promotion_id="promotion-1",
        trigger_id="trigger-1",
        promoted_turn_key=("conversation-1", 2),
        promotion_role=PromotionRole.AFTER,
        promoted_content_digest="digest",
    )

    assert trigger.to_dict()["source"] == "native"
    assert trigger.to_dict()["severity"] == "high"
    assert trigger.to_dict()["metadata"]["nested"]["severity"] == "low"
    assert promotion.to_dict()["promotion_role"] == "after"
    assert promotion.to_dict()["promoted_turn_key"] == ["conversation-1", 2]
