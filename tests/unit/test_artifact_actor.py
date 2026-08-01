from __future__ import annotations

import asyncio

import pytest

from adaptive_synth_eval.unified_eval.orchestrator.artifact_actor import ArtifactActor


@pytest.mark.asyncio
async def test_artifact_actor_serializes_submissions_and_acks_after_persistence():
    calls = []
    persisted = asyncio.Event()

    async def persist(sequence, persona_id, result):
        calls.append((sequence, persona_id, result))
        if sequence == 1:
            assert not persisted.is_set()
            persisted.set()

    actor = ArtifactActor(persist)
    first = asyncio.create_task(actor.submit(1, "P1", "first"))
    await persisted.wait()
    second = asyncio.create_task(actor.submit(2, "P2", "second"))
    await asyncio.gather(first, second)
    await actor.close()

    assert calls == [(1, "P1", "first"), (2, "P2", "second")]


@pytest.mark.asyncio
async def test_artifact_actor_persists_duplicate_sequence_exactly_once():
    calls = 0

    async def persist(sequence, persona_id, result):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)

    actor = ArtifactActor(persist)
    await asyncio.gather(
        actor.submit(1, "P1", "same result"),
        actor.submit(1, "P1", "same result"),
    )
    await actor.submit(1, "P1", "same result")
    await actor.close()

    assert calls == 1


@pytest.mark.asyncio
async def test_artifact_actor_propagates_fatal_failure_to_queued_submitters():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def persist(sequence, persona_id, result):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        raise OSError("disk full")

    actor = ArtifactActor(persist)
    first = asyncio.create_task(actor.submit(1, "P1", "first"))
    await entered.wait()
    second = asyncio.create_task(actor.submit(2, "P2", "second"))
    release.set()

    with pytest.raises(OSError, match="disk full"):
        await first
    with pytest.raises(OSError, match="disk full"):
        await second
    await actor.close()

    assert calls == 1


@pytest.mark.asyncio
async def test_artifact_actor_cancellation_is_not_swallowed_or_hung():
    entered = asyncio.Event()

    async def persist(sequence, persona_id, result):
        entered.set()
        await asyncio.Event().wait()

    actor = ArtifactActor(persist)
    submit = asyncio.create_task(actor.submit(1, "P1", "first"))
    await entered.wait()
    actor._task.cancel()
    await asyncio.sleep(0)

    assert actor._task.cancelled()
    with pytest.raises(asyncio.CancelledError):
        await actor.close()

    submit.cancel()
    with pytest.raises(asyncio.CancelledError):
        await submit


@pytest.mark.asyncio
async def test_artifact_actor_orders_profile_submissions_and_handles_resume_gaps():
    calls = []

    async def persist(sequence, persona_id, result):
        calls.append((sequence, result))

    actor = ArtifactActor(persist, expected_sequences=[2, 4])
    later = asyncio.create_task(actor.submit(4, "P1", "fourth"))
    await asyncio.sleep(0)
    assert calls == []
    earlier = asyncio.create_task(actor.submit(2, "P1", "second"))
    await asyncio.gather(earlier, later)
    await actor.close()

    assert calls == [(2, "second"), (4, "fourth")]


@pytest.mark.asyncio
async def test_artifact_actor_profile_skip_unblocks_a_later_result():
    calls = []

    async def persist(sequence, persona_id, result):
        calls.append(sequence)

    actor = ArtifactActor(persist, expected_sequences=[1, 2])
    later = asyncio.create_task(actor.submit(2, "P1", "second"))
    await asyncio.sleep(0)
    assert not later.done()

    await actor.skip(1)
    await later
    await actor.close()

    assert calls == [2]


@pytest.mark.asyncio
async def test_artifact_actor_close_fails_submit_waiting_on_missing_sequence():
    async def persist(sequence, persona_id, result):
        raise AssertionError("a later result must not bypass a missing sequence")

    actor = ArtifactActor(persist, expected_sequences=[1, 2])
    later = asyncio.create_task(actor.submit(2, "P1", "second"))
    await asyncio.sleep(0)

    try:
        with pytest.raises(RuntimeError, match="missing.*sequence 1"):
            await asyncio.wait_for(actor.close(), timeout=0.5)
        with pytest.raises(RuntimeError, match="missing.*sequence 1"):
            await asyncio.wait_for(later, timeout=0.5)
    finally:
        if not later.done():
            later.cancel()
        await asyncio.gather(later, return_exceptions=True)

    assert actor._task.done()


@pytest.mark.asyncio
async def test_artifact_actor_task_cancellation_releases_ordered_submitter():
    async def persist(sequence, persona_id, result):
        raise AssertionError("a later result must not bypass a missing sequence")

    actor = ArtifactActor(persist, expected_sequences=[1, 2])
    later = asyncio.create_task(actor.submit(2, "P1", "second"))
    await asyncio.sleep(0)

    actor._task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await actor.close()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(later, timeout=0.5)

    assert actor._task.done()
    assert later.done()
