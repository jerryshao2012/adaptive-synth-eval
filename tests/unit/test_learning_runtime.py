from __future__ import annotations

import pytest

from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.learning.experience import artifact_fingerprint
from adaptive_synth_eval.learning.models import LearningBundle
from adaptive_synth_eval.adversarial_response_engine.core.models import SessionState
from adaptive_synth_eval.adversarial_response_engine.engine.attack_agent import (
    AttackAgent,
)
from adaptive_synth_eval.unified_eval.config.contract import (
    contract_to_dict,
    load_unified_contract,
)
from adaptive_synth_eval.unified_eval.orchestrator.runner import (
    _validate_resume_fingerprints,
)


EXAMPLE = "contracts/examples/unified_evaluation_demo.yaml"


def test_learning_bundle_is_applied_and_fingerprinted_with_contract():
    baseline = load_unified_contract(EXAMPLE)
    baseline_payload = contract_to_dict(baseline)
    bundle = LearningBundle.create(
        profile_id="demo",
        parent_id=None,
        patch=[
            {
                "op": "replace",
                "path": "/eval_plan/entries/0/weight",
                "value": 0.4,
            }
        ],
        policy={"ucb_exploration_c": 2.1},
        provenance={"run_ids": ["run-1"]},
        created_at="2026-07-27T12:00:00+00:00",
    )

    learned = load_unified_contract(EXAMPLE, learning_bundle=bundle)
    learned_payload = contract_to_dict(learned)

    assert learned.eval_plan.entries[0].weight == 0.4
    assert learned.learning_policy["ucb_exploration_c"] == 2.1
    assert learned.learning_bundle["bundle_id"] == bundle.bundle_id
    assert learned.learning_bundle["digest"] == bundle.digest
    assert artifact_fingerprint(learned_payload) != artifact_fingerprint(
        baseline_payload
    )


def test_empty_bundle_still_changes_fingerprint_for_resume_safety():
    baseline = contract_to_dict(load_unified_contract(EXAMPLE))
    bundle = LearningBundle.create(
        profile_id="demo",
        parent_id=None,
        patch=[],
        policy={"ucb_exploration_c": 1.4},
        provenance={},
        created_at="2026-07-27T12:00:00+00:00",
    )

    learned = contract_to_dict(
        load_unified_contract(EXAMPLE, learning_bundle=bundle)
    )

    assert artifact_fingerprint(learned) != artifact_fingerprint(baseline)


def test_resume_rejects_a_different_resolved_learning_bundle():
    first = LearningBundle.create(
        profile_id="demo",
        parent_id=None,
        patch=[],
        policy={"ucb_exploration_c": 1.4},
        provenance={},
        created_at="2026-07-27T12:00:00+00:00",
    )
    second = LearningBundle.create(
        profile_id="demo",
        parent_id=first.bundle_id,
        patch=[],
        policy={"ucb_exploration_c": 2.0},
        provenance={},
        created_at="2026-07-27T13:00:00+00:00",
    )
    first_fingerprint = artifact_fingerprint(
        contract_to_dict(load_unified_contract(EXAMPLE, learning_bundle=first))
    )
    second_fingerprint = artifact_fingerprint(
        contract_to_dict(load_unified_contract(EXAMPLE, learning_bundle=second))
    )

    with pytest.raises(ContractError, match="effective contract differs"):
        _validate_resume_fingerprints(
            {
                "version": 2,
                "contract_fingerprint": first_fingerprint,
                "plan_fingerprint": "same-plan",
            },
            contract_fingerprint=second_fingerprint,
            plan_fingerprint="same-plan",
        )


def test_learning_policy_controls_attack_exploration(monkeypatch):
    captured = {}

    def select(_memory, _rng, **kwargs):
        captured.update(kwargs)
        return "authority"

    monkeypatch.setattr(
        "adaptive_synth_eval.adversarial_response_engine.engine.attack_agent.select_angle",
        select,
    )
    agent = AttackAgent(
        planner=None,
        generator=None,
        exploration_c=2.2,
    )

    assert (
        agent._select_session_angle(
            SessionState(session_id="s1", scenario="test")
        )
        == "authority"
    )
    assert captured["c"] == 2.2
