"""Durability and concurrency tests for capture storage."""

from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from adaptive_synth_eval.capture.models import (
    CaptureEnvelope,
    PromotionRecord,
    PromotionRole,
    SkeletonRecord,
)
from adaptive_synth_eval.capture.sinks import (
    CaptureCoordinator,
    JSONLCaptureSink,
    JSONLLocalCaptureBuffer,
)


def _envelope(index: int, producer: str = "target:default") -> CaptureEnvelope:
    return CaptureEnvelope(
        envelope_id=f"envelope-{index}",
        source_artifact="chat_history",
        producer_id=producer,
        conversation_id="conversation-1",
        turn_id=index,
        timestamp="2026-07-26T00:00:00Z",
        content={"index": index, "message": f"message-{index}"},
    )


def _write_skeleton_process(run_dir: str, start: int, count: int) -> None:
    sink = JSONLCaptureSink(Path(run_dir))
    for index in range(start, start + count):
        skeleton = SkeletonRecord(
            skeleton_id=f"process-skeleton-{index}",
            producer_id="target:default",
            conversation_id="conversation-1",
            turn_id=index,
            timestamp="2026-07-26T00:00:00Z",
            event_type="chat_history",
            content_digest=f"digest-{index}",
            content_size_bytes=index,
            buffer_locator=None,
            status="success",
        )
        sink.write_skeleton(skeleton)
        sink.write_skeleton(skeleton)


def test_file_buffer_survives_restart_and_evicts_fifo(tmp_path: Path) -> None:
    path = tmp_path / "capture" / "local" / "target-default.jsonl"
    buffer = JSONLLocalCaptureBuffer(path, max_records=3)
    locators = [buffer.buffer_envelope(_envelope(index)) for index in range(4)]

    restarted = JSONLLocalCaptureBuffer(path, max_records=3)
    assert restarted.resolve(locators[0]) is None
    assert restarted.resolve(locators[-1])["envelope_id"] == "envelope-3"
    assert [row["envelope_id"] for row in restarted.get_buffered()] == [
        "envelope-1",
        "envelope-2",
        "envelope-3",
    ]


def test_concurrent_sink_instances_append_without_loss_or_duplicates(
    tmp_path: Path,
) -> None:
    def write(index: int) -> None:
        sink = JSONLCaptureSink(tmp_path)
        skeleton = SkeletonRecord(
            skeleton_id=f"skeleton-{index}",
            producer_id="target:default",
            conversation_id="conversation-1",
            turn_id=index,
            timestamp="2026-07-26T00:00:00Z",
            event_type="chat_history",
            content_digest=f"digest-{index}",
            content_size_bytes=index,
            buffer_locator=None,
            status="success",
        )
        sink.write_skeleton(skeleton)
        sink.write_skeleton(skeleton)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(50)))

    path = tmp_path / "capture" / "skeleton.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 50
    assert len({row["skeleton_id"] for row in rows}) == 50
    assert not list(path.parent.glob("*.tmp"))


def test_concurrent_processes_append_without_loss_or_duplicates(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=_write_skeleton_process,
            args=(str(tmp_path), worker * 10, 10),
        )
        for worker in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    rows = [
        json.loads(line)
        for line in (tmp_path / "capture" / "skeleton.jsonl")
        .read_text()
        .splitlines()
    ]
    assert len(rows) == 40
    assert len({row["skeleton_id"] for row in rows}) == 40


def test_coordinator_persists_locator_and_resolves_promotion(tmp_path: Path) -> None:
    coordinator = CaptureCoordinator(tmp_path, max_records_per_producer=2)
    envelope = _envelope(1)

    skeleton = coordinator.emit_envelope(
        envelope,
        promote=False,
        producer_id=envelope.producer_id,
    )
    promotion = PromotionRecord(
        promotion_id="promotion-1",
        trigger_id="trigger-1",
        promoted_turn_key=("conversation-1", 1),
        promotion_role=PromotionRole.TRIGGER,
        promoted_content_digest=skeleton.content_digest,
    )
    result = coordinator.promote(promotion, skeleton.buffer_locator)

    assert skeleton.buffer_locator
    assert result.status == "promoted"
    assert (tmp_path / "capture" / "envelopes.jsonl").exists()
    rows = [
        json.loads(line)
        for line in (tmp_path / "capture" / "promotions.jsonl")
        .read_text()
        .splitlines()
    ]
    assert rows[0]["status"] == "promoted"


def test_restarted_coordinator_resolves_locator_from_skeleton(
    tmp_path: Path,
) -> None:
    first = CaptureCoordinator(tmp_path)
    skeleton = first.emit_envelope(_envelope(1), producer_id="target:default")
    first.close()

    restarted = CaptureCoordinator(tmp_path)
    locator = restarted.locator_for_envelope(skeleton.skeleton_id)
    assert locator == skeleton.buffer_locator

    promotion = PromotionRecord(
        promotion_id="promotion-after-restart",
        trigger_id="trigger-1",
        promoted_turn_key=("conversation-1", 1),
        promotion_role=PromotionRole.TRIGGER,
        promoted_content_digest=skeleton.content_digest,
    )
    assert restarted.promote(promotion, locator).status == "promoted"


def test_missing_locator_is_journaled_as_unresolved(tmp_path: Path) -> None:
    coordinator = CaptureCoordinator(tmp_path)
    promotion = PromotionRecord(
        promotion_id="promotion-missing",
        trigger_id="trigger-1",
        promoted_turn_key=("legacy-conversation", 1),
        promotion_role=PromotionRole.TRIGGER,
        promoted_content_digest="digest",
    )

    result = coordinator.promote(promotion, None)

    assert result.status == "unavailable_missing"
    row = json.loads(
        (tmp_path / "capture" / "promotions.jsonl").read_text().splitlines()[0]
    )
    assert row["status"] == "unavailable_missing"
