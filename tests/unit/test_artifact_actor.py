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
