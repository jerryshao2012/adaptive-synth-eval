from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from adaptive_synth_eval.learning.coordinator import (
    EvaluatorTournamentExecutor,
    LearningCoordinator,
)
from adaptive_synth_eval.loop.profiles import (
    LearningConfig,
    LearningTournamentConfig,
    LoopProfile,
    LoopTarget,
)


EXAMPLE = Path("contracts/examples/unified_evaluation_demo.yaml").resolve()


def _profile(*, enabled=True, min_runs=1, min_conversations=1):
    return LoopProfile(
        profile_id="demo",
        readiness_level="L2",
        cadence="hourly",
        targets=[LoopTarget(contract=str(EXAMPLE), dry_run=False)],
        source_path=Path("loops/profiles/demo.yaml").resolve(),
        learning=LearningConfig(
            enabled=enabled,
            min_new_runs=min_runs,
            min_new_adversarial_conversations=min_conversations,
            validation_contracts=(str(EXAMPLE),),
            tournament=LearningTournamentConfig(
                initial_pairs=20,
                batch_pairs=20,
                max_pairs=20,
            ),
        ),
    )


def _seed_ledger(output_dir: Path):
    ledger = output_dir / "learning" / "demo" / "experience.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "adversarial_conversations": 100,
                "failure_signatures": [],
                "coverage": {
                    "personas": {"P1": 100},
                    "scenarios": {"prompt-injection": 100},
                    "angles": {"authority": 100},
                },
                "judge_error_rate": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _execute(variant, _bundle, seed, pack, _contract):
    return {
        "variant": variant,
        "seed": seed,
        "pack": pack,
        "failure_signatures": (
            ["new-failure"]
            if variant == "challenger" and pack == "fresh"
            else []
        ),
        "detected": True,
        "judge_error": False,
        "tokens": 100,
        "coverage": {
            "personas": "P1",
            "scenarios": "prompt-injection",
            "angles": "authority",
        },
        "target_fingerprint": "target-v1",
    }


def test_learning_coordinator_creates_passed_candidate_without_activating(tmp_path):
    _seed_ledger(tmp_path)
    coordinator = LearningCoordinator(
        _profile(),
        output_dir=tmp_path,
        tournament_execute=_execute,
        proposal_fn=lambda _prompt: '{"patch": []}',
        target_fingerprint_override="target-v1",
        bootstrap_samples=100,
    )

    result = coordinator.run(run_dirs=[])

    assert result["status"] == "candidate_passed"
    assert result["evaluation"]["verdict"] == "passed"
    assert coordinator.registry.active_bundle() is None
    assert coordinator.registry.get_candidate(result["candidate_id"])["status"] == "passed"
    assert Path(result["evidence_report"]).exists()


def test_learning_coordinator_waits_for_threshold_without_candidate(tmp_path):
    _seed_ledger(tmp_path)
    coordinator = LearningCoordinator(
        _profile(min_runs=3),
        output_dir=tmp_path,
        tournament_execute=_execute,
        proposal_fn=lambda _prompt: '{"patch": []}',
    )

    result = coordinator.run(run_dirs=[])

    assert result["status"] == "waiting_for_evidence"
    assert result["eligible_runs"] == 1
    assert coordinator.registry.list_candidates() == []


def test_learning_coordinator_disabled_does_not_create_artifacts(tmp_path):
    coordinator = LearningCoordinator(
        _profile(enabled=False),
        output_dir=tmp_path,
        tournament_execute=_execute,
    )

    result = coordinator.run(run_dirs=[])

    assert result["status"] == "disabled"
    assert not (tmp_path / "learning").exists()


def test_tournament_run_ids_are_scoped_to_the_challenger(tmp_path):
    first = EvaluatorTournamentExecutor(
        _profile(), output_dir=tmp_path, tournament_id="candidate-a"
    )
    second = EvaluatorTournamentExecutor(
        _profile(), output_dir=tmp_path, tournament_id="candidate-b"
    )

    assert first._run_id("champion", "locked", 7) != second._run_id(
        "champion", "locked", 7
    )


def test_learning_coordinator_serializes_profile_cycles(tmp_path):
    _seed_ledger(tmp_path)
    active_proposals = 0
    maximum_active = 0
    mutex = threading.Lock()
    overlap = threading.Event()

    def proposal(_prompt):
        nonlocal active_proposals, maximum_active
        with mutex:
            active_proposals += 1
            maximum_active = max(maximum_active, active_proposals)
            if active_proposals > 1:
                overlap.set()
        overlap.wait(timeout=0.2)
        with mutex:
            active_proposals -= 1
        return '{"patch": []}'

    coordinators = [
        LearningCoordinator(
            _profile(),
            output_dir=tmp_path,
            tournament_execute=_execute,
            proposal_fn=proposal,
            target_fingerprint_override="target-v1",
            bootstrap_samples=100,
        )
        for _ in range(2)
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda coordinator: coordinator.run(run_dirs=[]), coordinators)
        )

    assert maximum_active == 1
    assert {result["status"] for result in results} == {
        "candidate_passed",
        "waiting_for_evidence",
    }
    assert len(coordinators[0].registry.list_candidates()) == 1


def test_learning_coordinator_passes_structural_taxonomy_to_tournament(
    tmp_path, monkeypatch
):
    _seed_ledger(tmp_path)
    captured = {}

    def tournament_run(_self, **kwargs):
        captured.update(kwargs)
        return {"verdict": "passed", "pairs": 20, "observations": []}

    monkeypatch.setattr(
        "adaptive_synth_eval.learning.coordinator.TournamentRunner.run",
        tournament_run,
    )
    coordinator = LearningCoordinator(
        _profile(),
        output_dir=tmp_path,
        proposal_fn=lambda _prompt: '{"patch": []}',
        target_fingerprint_override="target-v1",
    )

    coordinator.run(run_dirs=[])

    assert captured["enabled_taxonomy"]["personas"]
    assert captured["enabled_taxonomy"]["scenarios"]
    assert captured["enabled_taxonomy"]["angles"]
    assert captured["challenger_taxonomy"] == captured["enabled_taxonomy"]


def test_learning_coordinator_marks_tournament_error_failed_and_retries_evidence(
    tmp_path,
):
    _seed_ledger(tmp_path)

    def broken_execute(*_args):
        raise RuntimeError("target temporarily unavailable")

    first = LearningCoordinator(
        _profile(),
        output_dir=tmp_path,
        tournament_execute=broken_execute,
        proposal_fn=lambda _prompt: '{"patch": []}',
        target_fingerprint_override="target-v1",
    ).run(run_dirs=[])

    assert first["status"] == "candidate_failed"
    first_registry = LearningCoordinator(
        _profile(), output_dir=tmp_path
    ).registry
    assert (
        first_registry.get_candidate(first["candidate_id"])["status"]
        == "failed"
    )

    second = LearningCoordinator(
        _profile(),
        output_dir=tmp_path,
        tournament_execute=_execute,
        proposal_fn=lambda _prompt: '{"patch": []}',
        target_fingerprint_override="target-v1",
        bootstrap_samples=100,
    ).run(run_dirs=[])

    assert second["status"] == "candidate_passed"
    assert second["candidate_id"] != first["candidate_id"]


def test_learning_coordinator_consumes_evidence_that_produces_no_change(
    tmp_path,
):
    _seed_ledger(tmp_path)
    first_coordinator = LearningCoordinator(
        _profile(),
        output_dir=tmp_path,
        tournament_execute=_execute,
        proposal_fn=lambda _prompt: '{"patch": []}',
        target_fingerprint_override="target-v1",
        bootstrap_samples=100,
    )
    first = first_coordinator.run(run_dirs=[])
    first_coordinator.registry.approve(
        first["candidate_id"], actor="reviewer", reason="baseline"
    )
    ledger = tmp_path / "learning" / "demo" / "experience.jsonl"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "run_id": "run-2",
                    "adversarial_conversations": 100,
                    "failure_signatures": [],
                    "coverage": {
                        "personas": {"P1": 100},
                        "scenarios": {"prompt-injection": 100},
                        "angles": {"authority": 100},
                    },
                    "judge_error_rate": 0.0,
                }
            )
            + "\n"
        )

    coordinator = LearningCoordinator(
        _profile(),
        output_dir=tmp_path,
        tournament_execute=_execute,
        proposal_fn=lambda _prompt: '{"patch": []}',
        target_fingerprint_override="target-v1",
    )
    no_change = coordinator.run(run_dirs=[])
    next_cycle = coordinator.run(run_dirs=[])

    assert no_change["status"] == "no_candidate_change"
    assert coordinator.registry.get_candidate(no_change["candidate_id"])[
        "status"
    ] == "failed"
    assert next_cycle["status"] == "waiting_for_evidence"
