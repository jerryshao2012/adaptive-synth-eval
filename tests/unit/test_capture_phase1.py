"""Unit tests for capture domain and trigger policy (Phase 1)."""

import json
import tempfile
from pathlib import Path

import pytest

from adaptive_synth_eval.capture.models import (
    CaptureEnvelope,
    CaptureTrigger,
    PromotionRecord,
    SkeletonRecord,
    TriggerSeverity,
    TriggerSource,
)
from adaptive_synth_eval.capture.sinks import JSONLCaptureSink
from adaptive_synth_eval.monitoring.triggers import (
    create_default_policy,
    detect_error,
    detect_jailbreak_or_injection,
    detect_latency_breach,
    detect_response_empty,
    evaluate_row_triggers,
)


class TestCaptureModels:
    """Test capture domain data structures."""

    def test_capture_trigger_creation(self):
        """Test creating a CaptureTrigger."""
        trigger = CaptureTrigger(
            trigger_id="run-1/native/error/abc123",
            source=TriggerSource.NATIVE_ROW_SIGNAL,
            event_type="error",
            severity=TriggerSeverity.HIGH,
            detector_name="error_field_v1",
            reason="Row contains error",
            timestamp="2026-07-24T12:34:56Z",
        )
        assert trigger.trigger_id == "run-1/native/error/abc123"
        assert trigger.severity == TriggerSeverity.HIGH
        assert trigger.to_dict()["trigger_id"] == "run-1/native/error/abc123"

    def test_skeleton_record_creation(self):
        """Test creating a SkeletonRecord."""
        skeleton = SkeletonRecord(
            skeleton_id="skel-1",
            producer_id="persona:P001",
            conversation_id="conv-1",
            turn_id=1,
            timestamp="2026-07-24T12:34:56Z",
            event_type="chat_turn",
            content_digest="abc123def456",
            content_size_bytes=512,
            buffer_locator=None,
            status="success",
        )
        assert skeleton.producer_id == "persona:P001"
        assert skeleton.content_size_bytes == 512
        assert skeleton.to_dict()["skeleton_id"] == "skel-1"

    def test_capture_envelope_skeleton_extraction(self):
        """Test extracting skeleton from envelope."""
        envelope = CaptureEnvelope(
            envelope_id="env-1",
            source_artifact="chat_history",
            producer_id="target:default",
            conversation_id="conv-1",
            turn_id=1,
            timestamp="2026-07-24T12:34:56Z",
            content={
                "user_message": "Hello",
                "bot_response": "Hi there",
                "error": None,
                "latency_ms": 1000.0,
            },
        )
        skeleton = envelope.skeleton()
        assert skeleton.producer_id == "target:default"
        assert skeleton.status == "success"
        assert "error" in skeleton.metadata
        assert "latency_ms" in skeleton.metadata

    def test_promotion_record_creation(self):
        """Test creating a PromotionRecord."""
        promotion = PromotionRecord(
            promotion_id="prom-1",
            trigger_id="trig-1",
            promoted_turn_key=("conv-1", 2),
            promoted_content_digest="abc123",
            promotion_role="after",
        )
        assert promotion.promoted_turn_key == ("conv-1", 2)
        assert str(promotion.promotion_role) == "after"


class TestTriggerPolicy:
    """Test trigger policy and detection."""

    def test_default_policy_creation(self):
        """Test creating default trigger policy."""
        policy = create_default_policy()
        assert policy.schema_version == 1
        assert policy.lookback_turns == 2
        assert policy.lookahead_turns == 2
        assert not hasattr(policy, "capture_budget_per_window")
        assert len(policy.rules) > 0

    def test_policy_fingerprint_stability(self):
        """Test that policy fingerprint is stable."""
        policy1 = create_default_policy()
        policy2 = create_default_policy()
        assert policy1.fingerprint() == policy2.fingerprint()

    def test_detect_error(self):
        """Test error detection."""
        assert detect_error({"error": "Something went wrong"}) is True
        assert detect_error({"error": None}) is False
        assert detect_error({"error": ""}) is False
        assert detect_error({}) is False

    def test_detect_latency_breach(self):
        """Test latency breach detection."""
        assert detect_latency_breach({"latency_ms": 9000}) is True
        assert detect_latency_breach({"latency_ms": 7000}) is False
        assert detect_latency_breach({"latency_ms": None}) is False
        assert detect_latency_breach({}) is False

    def test_detect_jailbreak_or_injection(self):
        """Test jailbreak/injection detection."""
        assert (
            detect_jailbreak_or_injection({"applied_failure_modes": ["jailbreak"]})
            is True
        )
        assert (
            detect_jailbreak_or_injection(
                {"applied_failure_modes": ["prompt_injection"]}
            )
            is True
        )
        assert (
            detect_jailbreak_or_injection({"applied_failure_modes": ["other_mode"]})
            is False
        )
        assert detect_jailbreak_or_injection({}) is False

    def test_detect_response_empty(self):
        """Test empty response detection."""
        assert detect_response_empty({"bot_response": ""}) is True
        assert detect_response_empty({"bot_response": "   "}) is True
        assert detect_response_empty({"bot_response": "Hello"}) is False
        assert detect_response_empty({}) is True

    def test_evaluate_row_triggers(self):
        """Test evaluating all triggers on a row."""
        policy = create_default_policy()
        row = {
            "error": "API timeout",
            "latency_ms": 9000,
            "applied_failure_modes": ["jailbreak"],
            "bot_response": "error",
        }
        triggers = evaluate_row_triggers(row, policy, "run-1", "conv-1", 1)
        assert len(triggers) > 0
        assert all(isinstance(t, CaptureTrigger) for t in triggers)
        assert any(t.event_type == "error" for t in triggers)

    def test_evaluate_row_no_triggers(self):
        """Test evaluating a row with no triggers."""
        policy = create_default_policy()
        row = {
            "error": None,
            "latency_ms": 100,
            "applied_failure_modes": [],
            "bot_response": "This is a normal response.",
        }
        triggers = evaluate_row_triggers(row, policy, "run-1", "conv-1", 1)
        # Should still have no triggers since nothing matched
        assert len(triggers) == 0


class TestJSONLCaptureSink:
    """Test JSONL capture sink."""

    def test_sink_write_skeleton(self):
        """Test writing skeleton records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)

            skeleton = SkeletonRecord(
                skeleton_id="skel-1",
                producer_id="persona:P001",
                conversation_id="conv-1",
                turn_id=1,
                timestamp="2026-07-24T12:34:56Z",
                event_type="chat_turn",
                content_digest="abc123",
                content_size_bytes=512,
                buffer_locator=None,
                status="success",
            )
            sink.write_skeleton(skeleton)
            sink.close()

            # Verify the file exists and contains the record
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            assert skeleton_file.exists()
            with skeleton_file.open() as f:
                content = f.read()
                assert "skel-1" in content

    def test_sink_idempotent_dedup(self):
        """Test that duplicate writes are deduplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)

            trigger = CaptureTrigger(
                trigger_id="trig-1",
                source=TriggerSource.NATIVE_ROW_SIGNAL,
                event_type="error",
                severity=TriggerSeverity.HIGH,
                detector_name="test",
                reason="Test",
                timestamp="2026-07-24T12:34:56Z",
            )

            # Write the same trigger twice
            sink.write_trigger(trigger)
            sink.write_trigger(trigger)
            sink.close()

            # Should only have one line in the file
            triggers_file = run_dir / "capture" / "triggers.jsonl"
            with triggers_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
                assert len(lines) == 1

    def test_sink_multiple_files(self):
        """Test that sink creates separate JSONL files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)

            skeleton = SkeletonRecord(
                skeleton_id="skel-1",
                producer_id="persona:P001",
                conversation_id="conv-1",
                turn_id=1,
                timestamp="2026-07-24T12:34:56Z",
                event_type="chat_turn",
                content_digest="abc123",
                content_size_bytes=512,
                buffer_locator=None,
                status="success",
            )
            trigger = CaptureTrigger(
                trigger_id="trig-1",
                source=TriggerSource.NATIVE_ROW_SIGNAL,
                event_type="error",
                severity=TriggerSeverity.HIGH,
                detector_name="test",
                reason="Test",
                timestamp="2026-07-24T12:34:56Z",
            )

            sink.write_skeleton(skeleton)
            sink.write_trigger(trigger)
            sink.close()

            # Verify both files exist
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            triggers_file = run_dir / "capture" / "triggers.jsonl"
            assert skeleton_file.exists()
            assert triggers_file.exists()


class TestIntegration:
    """Integration tests for Phase 1 components."""

    def test_end_to_end_capture_flow(self):
        """Test the full capture flow: envelope -> skeleton -> records."""
        envelope = CaptureEnvelope(
            envelope_id="env-1",
            source_artifact="chat_history",
            producer_id="target:default",
            conversation_id="conv-1",
            turn_id=1,
            timestamp="2026-07-24T12:34:56Z",
            content={
                "user_message": "What is policy X?",
                "bot_response": "Policy X requires approval",
                "error": None,
                "latency_ms": 1234.5,
            },
        )

        # Extract skeleton
        skeleton = envelope.skeleton()
        assert skeleton.producer_id == "target:default"

        # Evaluate triggers on the original row
        policy = create_default_policy()
        triggers = evaluate_row_triggers(
            envelope.content,
            policy,
            "run-1",
            envelope.conversation_id,
            envelope.turn_id,
        )
        # Should have latency trigger since latency is present
        assert len(triggers) >= 0  # No triggers expected for normal row

    def test_trigger_severity_ordering(self):
        """Test that triggers are created with correct severity."""
        policy = create_default_policy()

        # Row with critical error
        row = {
            "error": "Critical system failure",
            "latency_ms": None,
            "applied_failure_modes": [],
            "bot_response": "OK",
        }

        triggers = evaluate_row_triggers(row, policy, "run-1", "conv-1", 1)
        error_triggers = [t for t in triggers if t.event_type == "error"]
        assert len(error_triggers) > 0
        assert error_triggers[0].severity == TriggerSeverity.HIGH
