"""Run-scoped actor that serializes artifact persistence and acknowledgements."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

PersistFn = Callable[[int, str, Any], Awaitable[None]]


@dataclass(frozen=True)
class _Submit:
    sequence: int
    persona_id: str
    result: Any
    future: asyncio.Future[None]


@dataclass(frozen=True)
class _Close:
    future: asyncio.Future[None]


@dataclass(frozen=True)
class _Skip:
    sequence: int
    future: asyncio.Future[None]


class ArtifactActor:
    """Own the ordered persistence side effects for one evaluation run."""

    def __init__(
        self, persist: PersistFn, *, expected_sequences: list[int] | None = None
    ):
        self._persist = persist
        self._queue: asyncio.Queue[_Submit | _Skip | _Close] = asyncio.Queue()
        self._failure: BaseException | None = None
        self._closed = False
        self._submissions: dict[int, tuple[str, Any, asyncio.Future[None]]] = {}
        self._expected_sequences = (
            deque(int(value) for value in expected_sequences)
            if expected_sequences is not None
            else None
        )
        self._pending_ordered: dict[int, _Submit] = {}
        self._skipped_sequences: set[int] = set()
        self._pending_acks: set[asyncio.Future[None]] = set()
        self._task = asyncio.create_task(self._run(), name="artifact-writer")

    def _new_ack(self) -> asyncio.Future[None]:
        future = asyncio.get_running_loop().create_future()
        self._pending_acks.add(future)
        future.add_done_callback(self._pending_acks.discard)
        return future

    @staticmethod
    def _fail_future(
        future: asyncio.Future[None], failure: BaseException
    ) -> None:
        if future.done():
            return
        if isinstance(failure, asyncio.CancelledError):
            future.cancel()
        else:
            future.set_exception(failure)

    def _fail_pending(self, failure: BaseException) -> None:
        for future in tuple(self._pending_acks):
            self._fail_future(future, failure)

    async def submit(self, sequence: int, persona_id: str, result: Any) -> None:
        if self._closed:
            raise RuntimeError("ArtifactActor is closed")
        sequence = int(sequence)
        persona_id = str(persona_id)
        existing = self._submissions.get(sequence)
        if existing is not None:
            existing_persona, existing_result, existing_future = existing
            if existing_persona != persona_id or existing_result != result:
                raise RuntimeError(
                    f"Conflicting artifact submission for sequence {sequence}"
                )
            await asyncio.shield(existing_future)
            return

        future = self._new_ack()
        self._submissions[sequence] = (persona_id, result, future)
        await self._queue.put(
            _Submit(
                sequence=sequence,
                persona_id=persona_id,
                result=result,
                future=future,
            )
        )
        await asyncio.shield(future)

    async def close(self) -> None:
        if self._task.done():
            self._closed = True
            await self._task
            return
        if self._closed:
            await self._task
            return
        self._closed = True
        future = self._new_ack()
        await self._queue.put(_Close(future=future))
        try:
            await asyncio.shield(future)
        finally:
            await self._task

    async def skip(self, sequence: int) -> None:
        """Mark a planned sequence as intentionally producing no artifact."""

        if self._expected_sequences is None:
            return
        if self._closed:
            raise RuntimeError("ArtifactActor is closed")
        future = self._new_ack()
        await self._queue.put(_Skip(sequence=int(sequence), future=future))
        await asyncio.shield(future)

    async def _run(self) -> None:
        try:
            while True:
                message = await self._queue.get()
                try:
                    if isinstance(message, _Close):
                        if self._expected_sequences is not None:
                            await self._flush_ordered()
                        if self._pending_ordered:
                            missing = (
                                self._expected_sequences[0]
                                if self._expected_sequences
                                else min(self._pending_ordered)
                            )
                            failure = RuntimeError(
                                "ArtifactActor closed with missing "
                                f"sequence {missing}; later submissions cannot be persisted"
                            )
                            self._failure = failure
                            self._fail_pending(failure)
                            self._pending_ordered.clear()
                            return
                        if not message.future.done():
                            message.future.set_result(None)
                        return
                    if isinstance(message, _Skip):
                        self._skipped_sequences.add(message.sequence)
                        await self._flush_ordered()
                        if not message.future.done():
                            message.future.set_result(None)
                        continue
                    if self._failure is not None:
                        self._fail_future(message.future, self._failure)
                        continue
                    if self._expected_sequences is not None:
                        self._pending_ordered[message.sequence] = message
                        await self._flush_ordered()
                        continue
                    try:
                        await self._persist(
                            message.sequence, message.persona_id, message.result
                        )
                    except Exception as exc:  # persist failure is fatal for this actor
                        self._failure = exc
                        self._fail_future(message.future, exc)
                    else:
                        if not message.future.done():
                            message.future.set_result(None)
                finally:
                    self._queue.task_done()
        except BaseException as exc:
            self._fail_pending(exc)
            raise

    async def _flush_ordered(self) -> None:
        assert self._expected_sequences is not None
        while self._expected_sequences:
            sequence = self._expected_sequences[0]
            if sequence in self._skipped_sequences:
                self._expected_sequences.popleft()
                self._skipped_sequences.remove(sequence)
                continue
            message = self._pending_ordered.get(sequence)
            if message is None:
                return
            self._expected_sequences.popleft()
            self._pending_ordered.pop(sequence, None)
            try:
                await self._persist(
                    message.sequence, message.persona_id, message.result
                )
            except Exception as exc:
                self._failure = exc
                if not message.future.done():
                    message.future.set_exception(exc)
                for pending in self._pending_ordered.values():
                    if not pending.future.done():
                        pending.future.set_exception(exc)
                self._pending_ordered.clear()
                return
            if not message.future.done():
                message.future.set_result(None)
