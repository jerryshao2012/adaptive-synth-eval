from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from adaptive_synth_eval.file_lock import file_lock
from adaptive_synth_eval.learning.models import LearningBundle, utc_now


class RegistryError(ValueError):
    """Base error for corrupt or invalid learning registry operations."""


class RegistryConflict(RegistryError):
    """Raised when a lifecycle or compare-and-swap precondition fails."""


class LearningRegistry:
    def __init__(self, output_dir: str | Path, profile_id: str) -> None:
        self.output_dir = Path(output_dir)
        self.profile_id = profile_id
        self.root = self.output_dir / "learning" / profile_id
        self.candidates_dir = self.root / "candidates"
        self.events_path = self.root / "decisions.jsonl"
        self.active_path = self.root / "active.json"
        self.lock_path = self.root / ".registry.lock"
        self.candidates_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with file_lock(self.lock_path):
            yield

    def create_candidate(self, bundle: LearningBundle) -> dict[str, Any]:
        if bundle.profile_id != self.profile_id:
            raise RegistryError(
                f"Bundle profile {bundle.profile_id!r} does not match registry {self.profile_id!r}"
            )
        candidate_id = f"candidate-{bundle.digest[:16]}"
        candidate_dir = self.candidates_dir / candidate_id
        with self._locked():
            if candidate_dir.exists():
                raise RegistryConflict(f"Candidate already exists: {candidate_id}")
            active = self._read_json(self.active_path)
            manifest = {
                "schema_version": 1,
                "candidate_id": candidate_id,
                "bundle_id": bundle.bundle_id,
                "bundle_digest": bundle.digest,
                "profile_id": self.profile_id,
                "parent_id": bundle.parent_id,
                "created_at": bundle.created_at,
                "expected_active_digest": (
                    None if active is None else active.get("digest")
                ),
            }
            candidate_dir.mkdir(parents=True)
            self._write_json_atomic(candidate_dir / "bundle.json", bundle.to_dict())
            self._write_json_atomic(candidate_dir / "manifest.json", manifest)
            self._write_json_atomic(candidate_dir / "diff.jsonpatch", bundle.patch)
            self._append_event(
                {
                    "event": "candidate_created",
                    "candidate_id": candidate_id,
                    "bundle_id": bundle.bundle_id,
                    "status": "draft",
                    "timestamp": utc_now(),
                }
            )
        return {**manifest, "status": "draft"}

    def mark_evaluating(self, candidate_id: str) -> dict[str, Any]:
        with self._locked():
            candidate = self._get_candidate_unlocked(candidate_id)
            if candidate["status"] != "draft":
                raise RegistryConflict(
                    f"Candidate must be draft before evaluation, got {candidate['status']}"
                )
            self._append_event(
                {
                    "event": "evaluation_started",
                    "candidate_id": candidate_id,
                    "bundle_id": candidate["bundle_id"],
                    "status": "evaluating",
                    "timestamp": utc_now(),
                }
            )
            return self._get_candidate_unlocked(candidate_id)

    def record_evaluation(
        self, candidate_id: str, evaluation: dict[str, Any]
    ) -> dict[str, Any]:
        verdict = str(evaluation.get("verdict") or "").lower()
        if verdict not in {"passed", "failed"}:
            raise RegistryError("Evaluation verdict must be passed or failed")
        with self._locked():
            candidate = self._get_candidate_unlocked(candidate_id)
            if candidate["status"] != "evaluating":
                raise RegistryConflict(
                    "Candidate must be evaluating before recording evidence"
                )
            evaluation_path = self.candidates_dir / candidate_id / "evaluation.json"
            if evaluation_path.exists():
                raise RegistryConflict("Candidate evaluation is immutable once recorded")
            self._write_json_atomic(evaluation_path, evaluation)
            self._append_event(
                {
                    "event": "evaluation_completed",
                    "candidate_id": candidate_id,
                    "bundle_id": candidate["bundle_id"],
                    "status": verdict,
                    "timestamp": utc_now(),
                }
            )
            return self._get_candidate_unlocked(candidate_id)

    def approve(
        self, candidate_id: str, *, actor: str, reason: str
    ) -> dict[str, Any]:
        self._require_decision_fields(actor, reason)
        with self._locked():
            candidate = self._get_candidate_unlocked(candidate_id)
            if candidate["status"] != "passed":
                raise RegistryConflict(
                    f"Candidate must have passed evidence before approval, got {candidate['status']}"
                )
            active = self._read_json(self.active_path)
            active_digest = None if active is None else active.get("digest")
            if active_digest != candidate.get("expected_active_digest"):
                raise RegistryConflict(
                    "Cannot approve candidate because the active bundle changed"
                )
            if active is not None:
                previous = self._candidate_for_bundle_unlocked(str(active["bundle_id"]))
                self._append_event(
                    {
                        "event": "superseded",
                        "candidate_id": previous["candidate_id"],
                        "bundle_id": previous["bundle_id"],
                        "status": "superseded",
                        "timestamp": utc_now(),
                        "superseded_by": candidate["bundle_id"],
                    }
                )
            timestamp = utc_now()
            self._append_event(
                {
                    "event": "approved",
                    "candidate_id": candidate_id,
                    "bundle_id": candidate["bundle_id"],
                    "status": "approved",
                    "timestamp": timestamp,
                    "actor": actor,
                    "reason": reason,
                }
            )
            pointer = {
                "profile_id": self.profile_id,
                "bundle_id": candidate["bundle_id"],
                "candidate_id": candidate_id,
                "digest": candidate["bundle_digest"],
                "activated_at": timestamp,
                "actor": actor,
                "reason": reason,
            }
            self._write_json_atomic(self.active_path, pointer)
            self._append_event(
                {
                    "event": "activated",
                    "candidate_id": candidate_id,
                    "bundle_id": candidate["bundle_id"],
                    "status": "active",
                    "timestamp": timestamp,
                    "actor": actor,
                }
            )
            return pointer

    def reject(
        self, candidate_id: str, *, actor: str, reason: str
    ) -> dict[str, Any]:
        self._require_decision_fields(actor, reason)
        with self._locked():
            candidate = self._get_candidate_unlocked(candidate_id)
            if candidate["status"] not in {
                "draft",
                "evaluating",
                "passed",
                "failed",
            }:
                raise RegistryConflict(
                    f"Candidate cannot be rejected from status {candidate['status']}"
                )
            self._append_event(
                {
                    "event": "rejected",
                    "candidate_id": candidate_id,
                    "bundle_id": candidate["bundle_id"],
                    "status": "rejected",
                    "timestamp": utc_now(),
                    "actor": actor,
                    "reason": reason,
                }
            )
            return self._get_candidate_unlocked(candidate_id)

    def rollback(
        self, *, to_bundle_id: str, actor: str, reason: str
    ) -> dict[str, Any]:
        self._require_decision_fields(actor, reason)
        with self._locked():
            target = self._candidate_for_bundle_unlocked(to_bundle_id)
            events = self._read_events()
            if not any(
                event.get("event") == "approved"
                and event.get("bundle_id") == to_bundle_id
                for event in events
            ):
                raise RegistryConflict(
                    "Rollback target must have a recorded human approval"
                )
            current = self._read_json(self.active_path)
            if current is not None and current.get("bundle_id") == to_bundle_id:
                raise RegistryConflict("Rollback target is already active")
            timestamp = utc_now()
            if current is not None:
                previous = self._candidate_for_bundle_unlocked(
                    str(current["bundle_id"])
                )
                self._append_event(
                    {
                        "event": "superseded",
                        "candidate_id": previous["candidate_id"],
                        "bundle_id": previous["bundle_id"],
                        "status": "superseded",
                        "timestamp": timestamp,
                        "superseded_by": to_bundle_id,
                    }
                )
            pointer = {
                "profile_id": self.profile_id,
                "bundle_id": target["bundle_id"],
                "candidate_id": target["candidate_id"],
                "digest": target["bundle_digest"],
                "activated_at": timestamp,
                "actor": actor,
                "reason": reason,
            }
            self._write_json_atomic(self.active_path, pointer)
            self._append_event(
                {
                    "event": "rollback",
                    "candidate_id": target["candidate_id"],
                    "bundle_id": target["bundle_id"],
                    "status": "active",
                    "timestamp": timestamp,
                    "actor": actor,
                    "reason": reason,
                    "from_bundle_id": (
                        None if current is None else current.get("bundle_id")
                    ),
                }
            )
            return pointer

    def active_bundle(self) -> LearningBundle | None:
        with self._locked():
            pointer = self._read_json(self.active_path)
            if pointer is None:
                return None
            candidate = self._candidate_for_bundle_unlocked(
                str(pointer["bundle_id"])
            )
            bundle = self._load_bundle(candidate["candidate_id"])
            if pointer.get("digest") != bundle.digest:
                raise RegistryError(
                    "Active pointer digest does not match the governed bundle"
                )
            return bundle

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        with self._locked():
            return self._get_candidate_unlocked(candidate_id)

    def list_candidates(self) -> list[dict[str, Any]]:
        with self._locked():
            return [
                self._get_candidate_unlocked(path.name)
                for path in sorted(self.candidates_dir.glob("candidate-*"))
                if path.is_dir()
            ]

    def bundle_for_candidate(self, candidate_id: str) -> LearningBundle:
        with self._locked():
            self._get_candidate_unlocked(candidate_id)
            return self._load_bundle(candidate_id)

    def audit(self) -> dict[str, Any]:
        issues: list[str] = []
        with self._locked():
            candidates = self.list_candidates_unlocked()
            for candidate in candidates:
                try:
                    bundle = self._load_bundle(candidate["candidate_id"])
                except (RegistryError, ValueError) as exc:
                    issues.append(str(exc))
                    continue
                if bundle.digest != candidate.get("bundle_digest"):
                    issues.append(
                        f"Bundle digest does not match manifest for {candidate['candidate_id']}"
                    )
            active = self._read_json(self.active_path)
            if active is not None:
                try:
                    candidate = self._candidate_for_bundle_unlocked(
                        str(active.get("bundle_id"))
                    )
                    if active.get("digest") != candidate.get("bundle_digest"):
                        issues.append("Active pointer digest does not match bundle")
                    events = self._read_events()
                    if not any(
                        event.get("event") == "approved"
                        and event.get("bundle_id") == active.get("bundle_id")
                        for event in events
                    ):
                        issues.append(
                            "Active bundle has no recorded human approval"
                        )
                except RegistryError as exc:
                    issues.append(str(exc))
            return {
                "profile_id": self.profile_id,
                "valid": not issues,
                "issues": issues,
                "candidate_count": len(candidates),
                "active": active,
            }

    def list_candidates_unlocked(self) -> list[dict[str, Any]]:
        return [
            self._get_candidate_unlocked(path.name)
            for path in sorted(self.candidates_dir.glob("candidate-*"))
            if path.is_dir()
        ]

    def _get_candidate_unlocked(self, candidate_id: str) -> dict[str, Any]:
        manifest_path = self.candidates_dir / candidate_id / "manifest.json"
        manifest = self._read_json(manifest_path)
        if manifest is None:
            raise RegistryError(f"Learning candidate not found: {candidate_id}")
        events = [
            event
            for event in self._read_events()
            if event.get("candidate_id") == candidate_id
        ]
        status = str(events[-1].get("status") if events else "draft")
        evaluation = self._read_json(
            self.candidates_dir / candidate_id / "evaluation.json"
        )
        return {**manifest, "status": status, "evaluation": evaluation}

    def _candidate_for_bundle_unlocked(self, bundle_id: str) -> dict[str, Any]:
        for path in self.candidates_dir.glob("candidate-*/manifest.json"):
            manifest = self._read_json(path)
            if manifest and manifest.get("bundle_id") == bundle_id:
                return self._get_candidate_unlocked(str(manifest["candidate_id"]))
        raise RegistryError(f"Learning bundle not found: {bundle_id}")

    def _load_bundle(self, candidate_id: str) -> LearningBundle:
        payload = self._read_json(
            self.candidates_dir / candidate_id / "bundle.json"
        )
        if payload is None:
            raise RegistryError(f"Bundle artifact missing for {candidate_id}")
        return LearningBundle.from_dict(payload)

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RegistryError("Learning decision log is corrupt") from exc
            if isinstance(event, dict):
                events.append(event)
        return events

    def _append_event(self, event: dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"Learning artifact is corrupt: {path}") from exc

    @staticmethod
    def _write_json_atomic(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(payload, indent=2, sort_keys=True, default=str)
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    @staticmethod
    def _require_decision_fields(actor: str, reason: str) -> None:
        if not actor.strip():
            raise RegistryError("Decision actor cannot be empty")
        if not reason.strip():
            raise RegistryError("Decision reason cannot be empty")


def load_bundle_reference(
    reference: str,
    *,
    output_dir: str | Path = "outputs",
) -> LearningBundle:
    explicit = Path(reference)
    if explicit.is_dir():
        explicit = explicit / "bundle.json"
    if explicit.exists():
        payload = json.loads(explicit.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RegistryError("Learning bundle file must contain an object")
        return LearningBundle.from_dict(payload)

    root = Path(output_dir) / "learning"
    matches: list[Path] = []
    if root.exists():
        for path in root.glob("*/candidates/*/bundle.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                payload.get("bundle_id") == reference
                or path.parent.name == reference
            ):
                matches.append(path)
    if not matches:
        raise RegistryError(f"Learning bundle not found: {reference}")
    if len(matches) > 1:
        raise RegistryConflict(
            f"Learning bundle reference is ambiguous: {reference}"
        )
    payload = json.loads(matches[0].read_text(encoding="utf-8"))
    return LearningBundle.from_dict(payload)
