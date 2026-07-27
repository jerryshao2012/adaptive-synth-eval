from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def digest_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class LearningBundle:
    bundle_id: str
    profile_id: str
    parent_id: str | None
    created_at: str
    patch: list[dict[str, Any]]
    policy: dict[str, Any]
    provenance: dict[str, Any]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        profile_id: str,
        parent_id: str | None,
        patch: list[dict[str, Any]],
        policy: dict[str, Any],
        provenance: dict[str, Any],
        created_at: str | None = None,
    ) -> "LearningBundle":
        timestamp = created_at or utc_now()
        content = {
            "profile_id": profile_id,
            "parent_id": parent_id,
            "created_at": timestamp,
            "patch": patch,
            "policy": policy,
            "provenance": provenance,
        }
        digest = digest_payload(content)
        return cls(
            bundle_id=f"bundle-{digest[:16]}",
            digest=digest,
            **content,
        )

    def content(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "patch": self.patch,
            "policy": self.policy,
            "provenance": self.provenance,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            **self.content(),
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LearningBundle":
        bundle = cls(
            bundle_id=str(payload["bundle_id"]),
            profile_id=str(payload["profile_id"]),
            parent_id=(
                None
                if payload.get("parent_id") is None
                else str(payload.get("parent_id"))
            ),
            created_at=str(payload["created_at"]),
            patch=[dict(item) for item in payload.get("patch") or []],
            policy=dict(payload.get("policy") or {}),
            provenance=dict(payload.get("provenance") or {}),
            digest=str(payload["digest"]),
        )
        expected = digest_payload(bundle.content())
        if expected != bundle.digest:
            raise ValueError(
                f"Learning bundle digest mismatch: expected {expected}, got {bundle.digest}"
            )
        if bundle.bundle_id != f"bundle-{expected[:16]}":
            raise ValueError("Learning bundle ID does not match its digest")
        return bundle
