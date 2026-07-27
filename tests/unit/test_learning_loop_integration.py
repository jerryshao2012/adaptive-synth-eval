from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from adaptive_synth_eval.cli import _run_loop_profile
from adaptive_synth_eval.learning.models import LearningBundle
from adaptive_synth_eval.learning.registry import LearningRegistry
from adaptive_synth_eval.loop.profiles import (
    LearningConfig,
    LoopProfile,
    LoopTarget,
)


def _profile(tmp_path):
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\neval_plan: {}\n", encoding="utf-8")
    return LoopProfile(
        profile_id="demo",
        readiness_level="L1",
        cadence="hourly",
        targets=[LoopTarget(contract=str(contract), dry_run=False)],
        source_path=tmp_path / "demo.yaml",
        learning=LearningConfig(
            enabled=True,
            min_new_runs=1,
            min_new_adversarial_conversations=1,
            validation_contracts=(str(contract),),
        ),
    )


def _activate_bundle(output_dir):
    registry = LearningRegistry(output_dir, "demo")
    bundle = LearningBundle.create(
        profile_id="demo",
        parent_id=None,
        patch=[],
        policy={"ucb_exploration_c": 2.0},
        provenance={},
    )
    candidate = registry.create_candidate(bundle)
    registry.mark_evaluating(candidate["candidate_id"])
    registry.record_evaluation(candidate["candidate_id"], {"verdict": "passed"})
    registry.approve(
        candidate["candidate_id"],
        actor="reviewer",
        reason="approved",
    )
    return bundle


def test_loop_resolves_active_bundle_once_and_runs_learning_after_reflection(
    tmp_path, monkeypatch
):
    output_dir = tmp_path / "outputs"
    bundle = _activate_bundle(output_dir)
    captured = {}
    profile = _profile(tmp_path)

    monkeypatch.setattr(
        "adaptive_synth_eval.cli._resolve_target_context",
        lambda _target: {
            "mode_name": "unified",
            "run_dir": None,
            "max_concurrency": 1,
        },
    )

    def execute(**kwargs):
        captured["bundle"] = kwargs["learning_bundle"]
        return {
            "run_id": "run-1",
            "completed_at": "2026-07-27T12:00:00+00:00",
            "errors": 0,
            "tokens": {"total_tokens": 10},
            "elapsed_seconds": 1.0,
            "output_dir": str(tmp_path / "run-1"),
        }

    monkeypatch.setattr("adaptive_synth_eval.cli._execute_contract_run", execute)
    monkeypatch.setattr(
        "adaptive_synth_eval.cli.LoopReasoner.plan_cycle",
        lambda self, state: SimpleNamespace(
            ai_reasoning="reason",
            ai_hypothesis=None,
            recommended_action="run",
            selected_targets=[profile.targets[0].__dict__],
            raw={},
            source="test",
        ),
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.cli.LoopReasoner.reflect_on_cycle",
        lambda self, state, runs, decision: SimpleNamespace(
            key_finding="ok",
            ai_reflection="ok",
            follow_up_enabled=False,
            escalation_items=[],
            raw={},
            source="test",
        ),
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.cli.LearningCoordinator.run",
        lambda self: {"status": "waiting_for_evidence"},
    )

    result = _run_loop_profile(
        profile,
        output_dir=output_dir,
        dry_run=False,
        incomplete_run_action="abort",
        realtime_chat=False,
        output_conversations=False,
    )

    assert captured["bundle"].digest == bundle.digest
    assert result["learning"]["status"] == "waiting_for_evidence"


def test_learning_failure_is_non_blocking_and_added_to_human_inbox(
    tmp_path, monkeypatch
):
    output_dir = tmp_path / "outputs"
    profile = _profile(tmp_path)
    monkeypatch.setattr(
        "adaptive_synth_eval.cli._resolve_target_context",
        lambda _target: {
            "mode_name": "unified",
            "run_dir": None,
            "max_concurrency": 1,
        },
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.cli._execute_contract_run",
        lambda **kwargs: {
            "run_id": "run-1",
            "completed_at": "2026-07-27T12:00:00+00:00",
            "errors": 0,
            "tokens": {},
            "output_dir": str(tmp_path / "run-1"),
        },
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.cli.LoopReasoner.plan_cycle",
        lambda self, state: SimpleNamespace(
            selected_targets=[profile.targets[0].__dict__],
            ai_reasoning="reason",
            ai_hypothesis=None,
            recommended_action="run",
            raw={},
            source="test",
        ),
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.cli.LoopReasoner.reflect_on_cycle",
        lambda self, state, runs, decision: SimpleNamespace(
            key_finding="ok",
            ai_reflection="ok",
            follow_up_enabled=False,
            escalation_items=[],
            raw={},
            source="test",
        ),
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.cli.LearningCoordinator.run",
        lambda self: (_ for _ in ()).throw(RuntimeError("candidate failed")),
    )

    result = _run_loop_profile(
        profile,
        output_dir=output_dir,
        dry_run=False,
        incomplete_run_action="abort",
        realtime_chat=False,
        output_conversations=False,
    )

    assert result["status"] == "completed"
    assert result["learning"]["status"] == "failed"
    assert "candidate failed" in result["learning"]["error"]
