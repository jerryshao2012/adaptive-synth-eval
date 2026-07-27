from __future__ import annotations

import pytest

from adaptive_synth_eval.learning.models import LearningBundle
from adaptive_synth_eval.learning.tournament import (
    PromotionVerifier,
    TournamentRunner,
)


def _bundle(name: str) -> LearningBundle:
    return LearningBundle.create(
        profile_id="demo",
        parent_id=None,
        patch=[],
        policy={"name": name},
        provenance={},
        created_at=f"2026-07-27T12:00:0{len(name)}+00:00",
    )


def _observation(
    variant: str,
    seed: int,
    pack: str,
    *,
    signatures=(),
    detected=True,
    judge_error=False,
    tokens=100,
    angle="authority",
    target_fingerprint="target-v1",
):
    return {
        "variant": variant,
        "seed": seed,
        "pack": pack,
        "failure_signatures": list(signatures),
        "detected": detected,
        "judge_error": judge_error,
        "tokens": tokens,
        "coverage": {
            "personas": "P1",
            "scenarios": "prompt-injection",
            "angles": angle,
        },
        "target_fingerprint": target_fingerprint,
    }


def test_promotion_verifier_requires_reproducible_novel_failure():
    pairs = []
    for seed in range(10):
        pairs.append(
            (
                _observation("champion", seed, "fresh", signatures=[]),
                _observation(
                    "challenger",
                    seed,
                    "fresh",
                    signatures=["new-failure"],
                ),
            )
        )

    result = PromotionVerifier(bootstrap_samples=200).evaluate(pairs)

    assert result["additional_reproducible_signatures"] == ["new-failure"]
    assert result["score_delta"] > 0
    assert result["confidence_interval"][0] > 0
    assert result["verdict"] == "passed"


def test_tournament_expands_in_batches_until_evidence_is_conclusive():
    calls = []

    def execute(variant, _bundle_value, seed, pack, _contract):
        calls.append((variant, seed, pack))
        signatures = []
        if variant == "challenger" and pack == "fresh" and seed >= 20:
            signatures = ["late-failure"]
        return _observation(
            variant,
            seed,
            pack,
            signatures=signatures,
        )

    result = TournamentRunner(
        execute=execute,
        initial_pairs=20,
        batch_pairs=20,
        max_pairs=100,
        bootstrap_samples=200,
    ).run(
        champion=_bundle("champion"),
        challenger=_bundle("challenger"),
        target_fingerprint="target-v1",
        validation_contracts=("locked.yaml",),
    )

    assert result["verdict"] == "passed"
    assert result["pairs"] == 40
    assert len(calls) == 80


@pytest.mark.parametrize(
    "challenger_kwargs,enabled_taxonomy,reason",
    [
        ({"detected": False}, None, "locked-pack detection"),
        ({"judge_error": True}, None, "judge error"),
        ({"tokens": 150}, None, "token cost"),
        (
            {"angle": "authority"},
            {"angles": {"authority", "roleplay"}},
            "taxonomy",
        ),
    ],
)
def test_promotion_verifier_rejects_hard_gate_regressions(
    challenger_kwargs, enabled_taxonomy, reason
):
    pairs = []
    for seed in range(20):
        pack = "locked" if seed % 2 == 0 else "fresh"
        pairs.append(
            (
                _observation(
                    "champion",
                    seed,
                    pack,
                    angle="roleplay" if seed % 3 == 0 else "authority",
                ),
                _observation(
                    "challenger",
                    seed,
                    pack,
                    signatures=["new"] if pack == "fresh" else [],
                    **challenger_kwargs,
                ),
            )
        )

    result = PromotionVerifier(bootstrap_samples=100).evaluate(
        pairs,
        enabled_taxonomy=enabled_taxonomy,
    )

    assert result["verdict"] == "failed"
    assert any(reason in item.lower() for item in result["gate_failures"])


def test_promotion_verifier_uses_declared_challenger_taxonomy():
    pairs = [
        (
            _observation("champion", seed, "locked", angle="authority"),
            _observation("challenger", seed, "locked", angle="authority"),
        )
        for seed in range(20)
    ]

    result = PromotionVerifier(bootstrap_samples=10).evaluate(
        pairs,
        enabled_taxonomy={"angles": {"authority", "roleplay"}},
        challenger_taxonomy={"angles": {"authority", "roleplay"}},
    )

    assert not any(
        "taxonomy" in failure.lower()
        for failure in result["gate_failures"]
    )


def test_tournament_fails_closed_at_max_pairs_when_inconclusive():
    def execute(variant, _bundle_value, seed, pack, _contract):
        return _observation(variant, seed, pack)

    result = TournamentRunner(
        execute=execute,
        initial_pairs=20,
        batch_pairs=20,
        max_pairs=40,
        bootstrap_samples=100,
    ).run(
        champion=_bundle("champion"),
        challenger=_bundle("challenger"),
        target_fingerprint="target-v1",
        validation_contracts=("locked.yaml",),
    )

    assert result["verdict"] == "failed"
    assert result["pairs"] == 40
    assert "inconclusive" in result["reason"].lower()


def test_tournament_stops_when_target_fingerprint_changes():
    def execute(variant, _bundle_value, seed, pack, _contract):
        fingerprint = "target-v2" if variant == "challenger" else "target-v1"
        return _observation(
            variant,
            seed,
            pack,
            target_fingerprint=fingerprint,
        )

    result = TournamentRunner(
        execute=execute,
        initial_pairs=20,
        batch_pairs=20,
        max_pairs=20,
        bootstrap_samples=100,
    ).run(
        champion=_bundle("champion"),
        challenger=_bundle("challenger"),
        target_fingerprint="target-v1",
        validation_contracts=("locked.yaml",),
    )

    assert result["verdict"] == "failed"
    assert result["pairs"] == 1
    assert "target fingerprint changed" in result["reason"].lower()
