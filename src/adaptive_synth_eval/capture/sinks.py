"""Durable local buffers and append-only journals for capture records."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from adaptive_synth_eval.file_lock import file_lock


def _payload(record: Any) -> dict[str, Any]:
    return record.to_dict() if hasattr(record, "to_dict") else dict(record)


def _json_line(record: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        + "\n"
    ).encode("utf-8")


class CaptureSink(Protocol):
    """Protocol for pluggable capture sinks."""

    def write_envelope(self, envelope: Any) -> None: ...

    def write_skeleton(self, skeleton: Any) -> None: ...

    def write_trigger(self, trigger: Any) -> None: ...

    def write_promotion(self, promotion: Any) -> None: ...

    def close(self) -> None: ...


class LocalCaptureBuffer(Protocol):
    """Protocol for a durable per-producer rich-record buffer."""

    def buffer_envelope(self, envelope: Any) -> str: ...

    def resolve(self, locator: str) -> dict[str, Any] | None: ...

    def get_buffered(self, limit: int | None = None) -> list[dict[str, Any]]: ...

    def clear(self) -> None: ...


class _AppendJournal:
    """A process- and thread-safe idempotent JSONL journal."""

    def __init__(self, path: Path, id_field: str):
        self.path = path
        self.id_field = id_field
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self._seen: set[str] = set()
        self._offset = 0

    def append(self, record: dict[str, Any]) -> bool:
        record_id = str(record[self.id_field])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.lock_path):
            self._refresh_seen()
            if record_id in self._seen:
                return False
            fd = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                line = _json_line(record)
                written = 0
                while written < len(line):
                    written += os.write(fd, line[written:])
                os.fsync(fd)
            finally:
                os.close(fd)
            self._seen.add(record_id)
            self._offset = self.path.stat().st_size
            return True

    def _refresh_seen(self) -> None:
        if not self.path.exists():
            self._offset = 0
            return
        size = self.path.stat().st_size
        if size < self._offset:
            self._seen.clear()
            self._offset = 0
        with self.path.open("rb") as journal:
            journal.seek(self._offset)
            for raw_line in journal:
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                value = row.get(self.id_field)
                if value is not None:
                    self._seen.add(str(value))
            self._offset = journal.tell()


class JSONLCaptureSink:
    """Concurrency-safe append-only capture journals."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.capture_dir = self.run_dir / "capture"
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.envelope_path = self.capture_dir / "envelopes.jsonl"
        self.skeleton_path = self.capture_dir / "skeleton.jsonl"
        self.triggers_path = self.capture_dir / "triggers.jsonl"
        self.promotions_path = self.capture_dir / "promotions.jsonl"
        # Backward-compatible attribute name used by the initial implementation.
        self.promoted_path = self.promotions_path
        self._journals = {
            "envelope": _AppendJournal(self.envelope_path, "envelope_id"),
            "skeleton": _AppendJournal(self.skeleton_path, "skeleton_id"),
            "trigger": _AppendJournal(self.triggers_path, "trigger_id"),
            "promotion": _AppendJournal(self.promotions_path, "promotion_id"),
        }

    def write_envelope(self, envelope: Any) -> None:
        self._journals["envelope"].append(_payload(envelope))

    def write_skeleton(self, skeleton: Any) -> None:
        self._journals["skeleton"].append(_payload(skeleton))

    def write_trigger(self, trigger: Any) -> None:
        self._journals["trigger"].append(_payload(trigger))

    def write_promotion(self, promotion: Any) -> None:
        self._journals["promotion"].append(_payload(promotion))

    def find_buffer_locator(self, skeleton_id: str) -> str | None:
        """Resolve the latest durable locator for a stable skeleton identifier."""
        if not self.skeleton_path.exists():
            return None
        match: str | None = None
        with file_lock(self._journals["skeleton"].lock_path, shared=True):
            with self.skeleton_path.open("r", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(row.get("skeleton_id")) == skeleton_id:
                        locator = row.get("buffer_locator")
                        match = str(locator) if locator else None
        return match

    def close(self) -> None:
        """The sink owns no persistent file handles."""


class JSONLLocalCaptureBuffer:
    """Bounded JSONL buffer with an atomic sidecar index."""

    def __init__(self, path: Path, max_records: int = 1000):
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self.path = Path(path)
        self.max_records = max_records
        self.index_path = self.path.with_suffix(self.path.suffix + ".index.json")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def buffer_envelope(self, envelope: Any) -> str:
        record = _payload(envelope)
        envelope_id = str(record["envelope_id"])
        with self._exclusive_lock():
            rows = self._read_rows_unlocked()
            rows = [
                existing
                for existing in rows
                if str(existing.get("envelope_id")) != envelope_id
            ]
            rows.append(record)
            rows = rows[-self.max_records :]
            self._rewrite_unlocked(rows)
        return f"{self.path}#{envelope_id}"

    def resolve(self, locator: str) -> dict[str, Any] | None:
        raw_path, separator, envelope_id = locator.rpartition("#")
        if not separator or Path(raw_path) != self.path:
            return None
        with self._exclusive_lock():
            index = self._read_index_unlocked()
            position = index.get(envelope_id)
            if position is None:
                return None
            rows = self._read_rows_unlocked()
            if position >= len(rows):
                return None
            row = rows[position]
            return row if str(row.get("envelope_id")) == envelope_id else None

    def get_buffered(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._exclusive_lock():
            rows = self._read_rows_unlocked()
        return rows[-limit:] if limit is not None else rows

    def clear(self) -> None:
        with self._exclusive_lock():
            self._rewrite_unlocked([])

    def _exclusive_lock(self):
        return file_lock(self.lock_path)

    def _read_rows_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as source:
            return [json.loads(line) for line in source if line.strip()]

    def _read_index_unlocked(self) -> dict[str, int]:
        if not self.index_path.exists():
            return {}
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(key): int(position) for key, position in value.items()}

    def _rewrite_unlocked(self, rows: list[dict[str, Any]]) -> None:
        self._atomic_replace(
            self.path,
            b"".join(_json_line(record) for record in rows),
        )
        index = {
            str(record["envelope_id"]): position for position, record in enumerate(rows)
        }
        self._atomic_replace(
            self.index_path,
            json.dumps(index, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )

    @staticmethod
    def _atomic_replace(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class InMemoryCaptureBuffer:
    """Compatibility-only bounded buffer used by external callers."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.buffer: list[dict[str, Any]] = []

    def buffer_envelope(self, envelope: Any, max_size: int | None = None) -> str:
        limit = max_size or self.max_size
        record = _payload(envelope)
        self.buffer = [
            row
            for row in self.buffer
            if row.get("envelope_id") != record.get("envelope_id")
        ]
        self.buffer.append(record)
        self.buffer = self.buffer[-limit:]
        return f"memory://{record['envelope_id']}"

    def resolve(self, locator: str) -> dict[str, Any] | None:
        envelope_id = locator.removeprefix("memory://")
        return next(
            (row for row in self.buffer if str(row.get("envelope_id")) == envelope_id),
            None,
        )

    def get_buffered(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.buffer[-limit:] if limit is not None else list(self.buffer)

    def clear(self) -> None:
        self.buffer.clear()


@dataclass(frozen=True)
class PromotionResult:
    """Outcome of resolving and journaling a promotion."""

    status: str
    promotion_id: str
    envelope_id: str | None = None


class CaptureCoordinator:
    """Run-scoped coordinator for durable buffers and capture journals."""

    def __init__(
        self,
        run_dir: Path,
        sink: CaptureSink | None = None,
        max_records_per_producer: int = 1000,
    ):
        self.run_dir = Path(run_dir)
        self.sink = sink or JSONLCaptureSink(run_dir)
        self.max_records_per_producer = max_records_per_producer
        self.local_buffers: dict[str, JSONLLocalCaptureBuffer] = {}

    def get_local_buffer(self, producer_id: str) -> JSONLLocalCaptureBuffer:
        if producer_id not in self.local_buffers:
            token = (
                re.sub(r"[^A-Za-z0-9._-]+", "-", producer_id).strip("-") or "producer"
            )
            path = self.run_dir / "capture" / "local" / f"{token}.jsonl"
            self.local_buffers[producer_id] = JSONLLocalCaptureBuffer(
                path,
                max_records=self.max_records_per_producer,
            )
        return self.local_buffers[producer_id]

    def emit_envelope(
        self,
        envelope: Any,
        promote: bool = False,
        producer_id: str | None = None,
    ) -> Any:
        producer = producer_id or getattr(envelope, "producer_id", None)
        locator = None
        if producer is not None:
            locator = self.get_local_buffer(producer).buffer_envelope(envelope)
        if promote:
            self.sink.write_envelope(envelope)
        skeleton = (
            envelope.skeleton(buffer_locator=locator)
            if hasattr(envelope, "skeleton")
            else None
        )
        if skeleton is not None:
            self.sink.write_skeleton(skeleton)
        return skeleton

    def emit_trigger(self, trigger: Any) -> None:
        self.sink.write_trigger(trigger)

    def emit_promotion(self, promotion: Any) -> None:
        self.sink.write_promotion(promotion)

    def locator_for_envelope(self, envelope_id: str) -> str | None:
        """Find a rich-buffer locator from the central skeleton journal."""
        resolver = getattr(self.sink, "find_buffer_locator", None)
        if not callable(resolver):
            return None
        return resolver(envelope_id)

    def promote(self, promotion: Any, locator: str | None) -> PromotionResult:
        promotion_payload = _payload(promotion)
        envelope = self._resolve_locator(locator) if locator else None
        if envelope is not None:
            self.sink.write_envelope(envelope)
            status = "promoted"
            envelope_id = str(envelope["envelope_id"])
        else:
            status = "unavailable_evicted" if locator else "unavailable_missing"
            envelope_id = None
        promotion_payload["status"] = status
        promotion_payload["buffer_locator"] = locator
        self.sink.write_promotion(promotion_payload)
        return PromotionResult(
            status=status,
            promotion_id=str(promotion_payload["promotion_id"]),
            envelope_id=envelope_id,
        )

    def _resolve_locator(self, locator: str) -> dict[str, Any] | None:
        raw_path, separator, _ = locator.rpartition("#")
        if not separator:
            return None
        path = Path(raw_path)
        buffer = next(
            (
                candidate
                for candidate in self.local_buffers.values()
                if candidate.path == path
            ),
            None,
        )
        if buffer is None:
            buffer = JSONLLocalCaptureBuffer(
                path,
                max_records=self.max_records_per_producer,
            )
        return buffer.resolve(locator)

    def close(self) -> None:
        self.sink.close()
