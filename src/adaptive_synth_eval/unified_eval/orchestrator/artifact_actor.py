"""Run-scoped actor that serializes artifact persistence and acknowledgements."""

from __future__ import annotations

import asyncio
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


class ArtifactActor:
    """Own the ordered persistence side effects for one evaluation run."""

    def __init__(self, persist: PersistFn):
        self._persist = persist
        self._queue: asyncio.Queue[_Submit | _Close] = asyncio.Queue()
        self._failure: BaseException | None = None
        self._closed = False
        self._submissions: dict[int, tuple[str, Any, asyncio.Future[None]]] = {}
        self._task = asyncio.create_task(self._run(), name="artifact-writer")

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

        future = asyncio.get_running_loop().create_future()
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
        future = asyncio.get_running_loop().create_future()
        await self._queue.put(_Close(future=future))
        await future
        await self._task

    async def _run(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                if isinstance(message, _Close):
                    if not message.future.done():
                        message.future.set_result(None)
                    return
                if self._failure is not None:
                    if not message.future.done():
                        message.future.set_exception(self._failure)
                    continue
                try:
                    await self._persist(
                        message.sequence, message.persona_id, message.result
                    )
                except Exception as exc:  # persist failure is fatal for this actor
                    self._failure = exc
                    if not message.future.done():
                        message.future.set_exception(exc)
                else:
                    if not message.future.done():
                        message.future.set_result(None)
            finally:
                self._queue.task_done()
