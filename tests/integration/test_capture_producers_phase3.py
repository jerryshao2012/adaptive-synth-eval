"""Integration tests for producer adapters (Phase 3)."""

import tempfile
from pathlib import Path

import pytest

from adaptive_synth_eval.capture.producers import (
    AttackMemoryProducerAdapter,
    ChatHistoryProducerAdapter,
    PersonaMemoryProducerAdapter,
)
from adaptive_synth_eval.capture.sinks import CaptureCoordinator, JSONLCaptureSink


class TestChatHistoryProducerAdapter:
    """Tests for chat history capture emission."""

    def test_emit_chat_turn_creates_envelope(self):
        """Test that chat turn emission creates a proper envelope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            adapter = ChatHistoryProducerAdapter(coordinator)

            content = {
                "user_message": "What is policy X?",
                "bot_response": "Policy X requires approval",
                "latency_ms": 1234.5,
                "error": None,
            }

            adapter.emit_chat_turn(
                conversation_id="conv-1",
                turn_id=1,
                producer_id="target:default",
                content=content,
            )

            coordinator.close()

            # Verify skeleton was written
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            assert skeleton_file.exists()

            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) >= 1

    def test_emit_chat_turn_without_coordinator_no_error(self):
        """Test that emission without coordinator gracefully does nothing."""
        adapter = ChatHistoryProducerAdapter(coordinator=None)

        # Should not raise
        adapter.emit_chat_turn(
            conversation_id="conv-1",
            turn_id=1,
            producer_id="target:default",
            content={"bot_response": "test"},
        )

    def test_emit_multiple_chat_turns_per_conversation(self):
        """Test emitting multiple turns from one conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            adapter = ChatHistoryProducerAdapter(coordinator)

            # Emit 5 turns
            for turn_id in range(1, 6):
                content = {
                    "user_message": f"Question {turn_id}",
                    "bot_response": f"Answer {turn_id}",
                    "latency_ms": 100 * turn_id,
                    "error": None,
                }
                adapter.emit_chat_turn(
                    conversation_id="conv-1",
                    turn_id=turn_id,
                    producer_id="target:default",
                    content=content,
                )

            coordinator.close()

            # Verify all 5 skeletons were written
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) == 5


class TestPersonaMemoryProducerAdapter:
    """Tests for persona memory capture emission."""

    def test_emit_memory_commit_creates_envelope(self):
        """Test that memory commit creates a proper envelope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            adapter = PersonaMemoryProducerAdapter(coordinator)

            memory_delta = {
                "demographics": {"role": "HR Manager", "seniority": "senior"},
                "preferences": ["email_summary", "weekly_reports"],
                "recent_window": [
                    {
                        "turn_id": 1,
                        "importance": "high",
                        "summary": "Asked about benefits",
                    },
                ],
            }

            adapter.emit_memory_commit(
                conversation_id="conv-1",
                persona_id="P001",
                memory_delta=memory_delta,
            )

            coordinator.close()

            # Verify skeleton was written
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            assert skeleton_file.exists()

            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) >= 1

    def test_memory_commit_per_conversation(self):
        """Test emitting memory commits for multiple conversations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            adapter = PersonaMemoryProducerAdapter(coordinator)

            # Emit memory commits for 3 conversations
            for conv_num in range(1, 4):
                memory_delta = {
                    "demographics": {"seniority": f"level-{conv_num}"},
                    "learned_facts": [f"fact-{conv_num}"],
                }
                adapter.emit_memory_commit(
                    conversation_id=f"conv-{conv_num}",
                    persona_id="P001",
                    memory_delta=memory_delta,
                )

            coordinator.close()

            # Verify all 3 skeletons were written
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) == 3

    def test_emit_memory_without_coordinator_no_error(self):
        """Test that emission without coordinator gracefully does nothing."""
        adapter = PersonaMemoryProducerAdapter(coordinator=None)

        # Should not raise
        adapter.emit_memory_commit(
            conversation_id="conv-1",
            persona_id="P001",
            memory_delta={"demographics": {"role": "test"}},
        )


class TestAttackMemoryProducerAdapter:
    """Tests for attack memory capture emission."""

    def test_emit_attack_memory_commit_creates_envelope(self):
        """Test that attack memory session creates a proper envelope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            adapter = AttackMemoryProducerAdapter(coordinator)

            attack_session = {
                "session_id": "atk-001",
                "strategy_instruction": "Try to escalate privileges",
                "failure_score": 0.75,
                "effective_failure_score": 0.80,
                "near_miss": True,
                "angle": "social_engineering",
                "sub_tactic": "authority_impersonation",
            }

            adapter.emit_attack_memory_commit(
                conversation_id="conv-1",
                persona_id="P001",
                attack_session=attack_session,
            )

            coordinator.close()

            # Verify skeleton was written
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            assert skeleton_file.exists()

            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) >= 1

    def test_attack_memory_per_conversation(self):
        """Test emitting attack sessions for multiple conversations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            adapter = AttackMemoryProducerAdapter(coordinator)

            # Emit attack sessions for 3 conversations
            for conv_num in range(1, 4):
                attack_session = {
                    "session_id": f"atk-{conv_num}",
                    "strategy_instruction": f"Attack strategy {conv_num}",
                    "failure_score": 0.5 + (conv_num * 0.1),
                    "angle": f"angle-{conv_num}",
                }
                adapter.emit_attack_memory_commit(
                    conversation_id=f"conv-{conv_num}",
                    persona_id="P001",
                    attack_session=attack_session,
                )

            coordinator.close()

            # Verify all 3 skeletons were written
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) == 3

    def test_emit_attack_without_coordinator_no_error(self):
        """Test that emission without coordinator gracefully does nothing."""
        adapter = AttackMemoryProducerAdapter(coordinator=None)

        # Should not raise
        adapter.emit_attack_memory_commit(
            conversation_id="conv-1",
            persona_id="P001",
            attack_session={"session_id": "test"},
        )


class TestProducerCoordination:
    """Integration tests for multiple producers emitting together."""

    def test_multiple_producers_emit_to_same_sink(self):
        """Test that multiple producers can emit to the same coordinator/sink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            chat_adapter = ChatHistoryProducerAdapter(coordinator)
            memory_adapter = PersonaMemoryProducerAdapter(coordinator)
            attack_adapter = AttackMemoryProducerAdapter(coordinator)

            # Emit from all three producers
            chat_adapter.emit_chat_turn(
                conversation_id="conv-1",
                turn_id=1,
                producer_id="target:default",
                content={"bot_response": "Hello"},
            )

            memory_adapter.emit_memory_commit(
                conversation_id="conv-1",
                persona_id="P001",
                memory_delta={"role": "test"},
            )

            attack_adapter.emit_attack_memory_commit(
                conversation_id="conv-1",
                persona_id="P001",
                attack_session={"session_id": "atk-1"},
            )

            coordinator.close()

            # Verify all 3 types were written
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) == 3

    def test_producer_per_conversation_conversation_isolation(self):
        """Test that different conversations don't interfere in per-producer buffers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            adapter = ChatHistoryProducerAdapter(coordinator)

            # Emit turns from 3 different conversations
            for conv_num in range(1, 4):
                for turn_num in range(1, 4):
                    adapter.emit_chat_turn(
                        conversation_id=f"conv-{conv_num}",
                        turn_id=turn_num,
                        producer_id="target:default",
                        content={"bot_response": f"Response from conv {conv_num}"},
                    )

            coordinator.close()

            # Verify all 9 turns were written (3 conversations × 3 turns)
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) == 9

    def test_producer_idempotent_re_emission(self):
        """Test that re-emitting the same envelope is idempotent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            sink = JSONLCaptureSink(run_dir)
            coordinator = CaptureCoordinator(run_dir, sink)

            adapter = ChatHistoryProducerAdapter(coordinator)

            content = {"bot_response": "Test response"}

            # Emit the same turn twice
            for _ in range(2):
                adapter.emit_chat_turn(
                    conversation_id="conv-1",
                    turn_id=1,
                    producer_id="target:default",
                    content=content,
                )

            coordinator.close()

            # Should have only 1 skeleton (idempotent)
            skeleton_file = run_dir / "capture" / "skeleton.jsonl"
            with skeleton_file.open() as f:
                lines = [l.strip() for l in f if l.strip()]
            # Stable turn identity is idempotent across retries.
            assert len(lines) == 1
