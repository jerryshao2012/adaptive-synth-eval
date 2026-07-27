from __future__ import annotations

import json

import pytest

from adaptive_synth_eval.learning.models import LearningBundle
from adaptive_synth_eval.learning.registry import (
    LearningRegistry,
    RegistryConflict,
    RegistryError,
)


def _bundle(profile_id: str, *, parent_id: str | None = None, weight: int = 1) -> LearningBundle:
    return LearningBundle.create(
        profile_id=profile_id,
        parent_id=parent_id,
        patch=[
            {
                "op": "replace",
                "path": "/eval_plan/recipes/0/weight",
                "value": weight,
            }
        ],
        policy={"ucb_exploration_c": 1.4},
        provenance={"run_ids": ["run-1"]},
    )


def test_learning_bundle_digest_is_canonical():
    left = LearningBundle.create(
        profile_id="demo",
        parent_id=None,
        patch=[{"path": "/x", "value": {"b": 2, "a": 1}, "op": "add"}],
        policy={"z": 1, "a": 2},
        provenance={"run_ids": ["run-1"]},
        created_at="2026-07-27T12:00:00+00:00",
    )
    right = LearningBundle.create(
        profile_id="demo",
        parent_id=None,
        patch=[{"op": "add", "value": {"a": 1, "b": 2}, "path": "/x"}],
        policy={"a": 2, "z": 1},
        provenance={"run_ids": ["run-1"]},
        created_at="2026-07-27T12:00:00+00:00",
    )

    assert left.digest == right.digest
    assert left.bundle_id == right.bundle_id


def test_registry_requires_passing_evidence_before_activation(tmp_path):
    registry = LearningRegistry(tmp_path / "outputs", "demo")
    bundle = _bundle("demo")
    candidate = registry.create_candidate(bundle)

    with pytest.raises(RegistryConflict, match="passed"):
        registry.approve(
            candidate["candidate_id"],
            actor="reviewer",
            reason="looks good",
        )

    registry.mark_evaluating(candidate["candidate_id"])
    registry.record_evaluation(
        candidate["candidate_id"],
        {
            "verdict": "passed",
            "pairs": 20,
            "target_fingerprint": "target-v1",
        },
    )
    active = registry.approve(
        candidate["candidate_id"],
        actor="reviewer",
        reason="validated",
    )

    assert active["bundle_id"] == bundle.bundle_id
    assert registry.get_candidate(candidate["candidate_id"])["status"] == "active"
    assert registry.active_bundle().digest == bundle.digest


def test_registry_stale_approval_cannot_replace_new_active_bundle(tmp_path):
    registry = LearningRegistry(tmp_path / "outputs", "demo")
    first = registry.create_candidate(_bundle("demo", weight=1))
    second = registry.create_candidate(_bundle("demo", weight=2))
    for candidate in (first, second):
        registry.mark_evaluating(candidate["candidate_id"])
        registry.record_evaluation(candidate["candidate_id"], {"verdict": "passed"})

    registry.approve(first["candidate_id"], actor="alice", reason="first winner")

    with pytest.raises(RegistryConflict, match="active bundle changed"):
        registry.approve(second["candidate_id"], actor="bob", reason="stale decision")


def test_registry_rollback_reactivates_previously_approved_bundle(tmp_path):
    registry = LearningRegistry(tmp_path / "outputs", "demo")
    first_bundle = _bundle("demo", weight=1)
    first = registry.create_candidate(first_bundle)
    registry.mark_evaluating(first["candidate_id"])
    registry.record_evaluation(first["candidate_id"], {"verdict": "passed"})
    registry.approve(first["candidate_id"], actor="alice", reason="baseline")

    second_bundle = _bundle("demo", parent_id=first_bundle.bundle_id, weight=2)
    second = registry.create_candidate(second_bundle)
    registry.mark_evaluating(second["candidate_id"])
    registry.record_evaluation(second["candidate_id"], {"verdict": "passed"})
    registry.approve(second["candidate_id"], actor="alice", reason="challenger")

    active = registry.rollback(
        to_bundle_id=first_bundle.bundle_id,
        actor="alice",
        reason="regression observed",
    )

    assert active["bundle_id"] == first_bundle.bundle_id
    assert registry.active_bundle().bundle_id == first_bundle.bundle_id
    events = [
        json.loads(line)
        for line in registry.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "rollback"
    assert events[-1]["reason"] == "regression observed"


def test_registry_audit_detects_tampered_bundle(tmp_path):
    registry = LearningRegistry(tmp_path / "outputs", "demo")
    candidate = registry.create_candidate(_bundle("demo"))
    clean = registry.audit()
    assert clean["valid"] is True

    bundle_path = (
        registry.candidates_dir / candidate["candidate_id"] / "bundle.json"
    )
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    payload["policy"]["ucb_exploration_c"] = 9.9
    bundle_path.write_text(json.dumps(payload), encoding="utf-8")

    report = registry.audit()

    assert report["valid"] is False
    assert any("digest" in issue.lower() for issue in report["issues"])


def test_registry_refuses_tampered_active_pointer(tmp_path):
    registry = LearningRegistry(tmp_path / "outputs", "demo")
    candidate = registry.create_candidate(_bundle("demo"))
    registry.mark_evaluating(candidate["candidate_id"])
    registry.record_evaluation(candidate["candidate_id"], {"verdict": "passed"})
    registry.approve(candidate["candidate_id"], actor="alice", reason="valid")
    pointer = json.loads(registry.active_path.read_text(encoding="utf-8"))
    pointer["digest"] = "tampered"
    registry.active_path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(RegistryError, match="Active pointer digest"):
        registry.active_bundle()
