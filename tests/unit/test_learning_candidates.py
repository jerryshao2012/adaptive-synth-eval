from __future__ import annotations

import pytest
import yaml

from adaptive_synth_eval.learning.candidates import (
    CandidateGenerator,
    CandidateValidationError,
    CandidateValidator,
)


def _base_contract():
    return {
        "persona_pool": [
            {"persona_id": "P1", "role": "employee"},
        ],
        "scenario_catalog": [
            {
                "scenario_id": "ADV1",
                "scenario_type": "prompt-injection",
                "scenario_text": "baseline",
            }
        ],
        "eval_plan": {"recipes": [{"recipe_id": "R1", "weight": 1.0}]},
        "target": {"mode": "dry_run"},
    }


@pytest.mark.parametrize(
    "patch,match",
    [
        (
            [{"op": "replace", "path": "/target/mode", "value": "llm"}],
            "forbidden",
        ),
        (
            [
                {
                    "op": "add",
                    "path": "/persona_pool/-",
                    "value": {
                        "persona_id": "P2",
                        "role": "employee",
                        "api_key": "sk-super-secret-value",
                    },
                }
            ],
            "secret",
        ),
        (
            [
                {
                    "op": "add",
                    "path": "/scenario_catalog/-",
                    "value": {
                        "scenario_id": "ADV1",
                        "scenario_type": "prompt-injection",
                        "scenario_text": "duplicate",
                    },
                }
            ],
            "duplicate",
        ),
    ],
)
def test_candidate_validator_rejects_unsafe_patches(patch, match):
    with pytest.raises(CandidateValidationError, match=match):
        CandidateValidator().validate(patch, base_contract=_base_contract())


def test_candidate_validator_enforces_bounded_asset_changes():
    patch = [
        {
            "op": "add",
            "path": "/persona_pool/-",
            "value": {"persona_id": f"P{index}", "role": "employee"},
        }
        for index in range(2, 5)
    ]

    with pytest.raises(CandidateValidationError, match="at most 2 personas"):
        CandidateValidator().validate(patch, base_contract=_base_contract())


@pytest.mark.parametrize(
    "patch",
    [
        [
            {
                "op": "replace",
                "path": "/persona_pool",
                "value": [],
            }
        ],
        [
            {
                "op": "replace",
                "path": "/eval_plan/recipes/0/recipe_id",
                "value": "redirected",
            }
        ],
    ],
)
def test_candidate_validator_rejects_collection_replacement_and_recipe_rewiring(
    patch,
):
    with pytest.raises(CandidateValidationError, match="forbidden"):
        CandidateValidator().validate(patch, base_contract=_base_contract())


def test_candidate_validator_enforces_configured_candidate_kinds():
    patch = [
        {
            "op": "add",
            "path": "/persona_pool/-",
            "value": {"persona_id": "P2", "role": "manager"},
        }
    ]

    with pytest.raises(CandidateValidationError, match="candidate kind"):
        CandidateValidator(candidate_kinds=("policy",)).validate(
            patch, base_contract=_base_contract()
        )


def test_candidate_validator_cannot_replace_existing_asset_identity():
    patch = [
        {
            "op": "replace",
            "path": "/persona_pool/0",
            "value": {"persona_id": "P2", "role": "manager"},
        }
    ]

    with pytest.raises(CandidateValidationError, match="remove or rename"):
        CandidateValidator().validate(patch, base_contract=_base_contract())


def test_candidate_validator_rejects_assets_that_break_unified_schema():
    base_path = "contracts/examples/unified_evaluation_demo.yaml"
    with open(base_path, encoding="utf-8") as handle:
        base_contract = yaml.safe_load(handle)
    patch = [
        {
            "op": "add",
            "path": "/persona_pool/-",
            "value": {"persona_id": "INCOMPLETE", "role": "employee"},
        }
    ]

    with pytest.raises(CandidateValidationError, match="schema"):
        CandidateValidator().validate(
            patch,
            base_contract=base_contract,
        )


def test_candidate_generator_falls_back_to_policy_when_llm_json_is_invalid():
    prompts = []

    def invalid_proposal(prompt: str) -> str:
        prompts.append(prompt)
        return "not-json"

    experiences = [
        {
            "run_id": "run-1",
            "failure_signatures": [
                {
                    "signature": "opaque-digest",
                    "components": {
                        "failure_type": "unsafe disclosure",
                        "attack_angle": "authority",
                        "sub_tactic": "manager escalation",
                    },
                    "conversation_id": "must-not-leak",
                }
            ],
            "coverage": {
                "personas": {"P1": 10},
                "scenarios": {"prompt-injection": 10},
                "angles": {"authority": 10},
            },
        }
    ]
    generator = CandidateGenerator(proposal_fn=invalid_proposal)

    bundle = generator.generate(
        profile_id="demo",
        parent_id=None,
        base_contract=_base_contract(),
        experiences=experiences,
    )

    assert bundle.patch == []
    assert bundle.policy["ucb_exploration_c"] > 1.4
    assert bundle.provenance["asset_proposal_status"] == "invalid_json"
    assert "validation_contract" not in prompts[0]
    assert "scenario_text" not in prompts[0]
    assert "unsafe disclosure" in prompts[0]
    assert "manager escalation" in prompts[0]
    assert "must-not-leak" not in prompts[0]


def test_candidate_generator_accepts_strict_bounded_asset_json():
    def proposal(_prompt: str) -> str:
        return """
        {
          "patch": [
            {
              "op": "add",
              "path": "/persona_pool/-",
              "value": {"persona_id": "P2", "role": "manager"}
            }
          ]
        }
        """

    generator = CandidateGenerator(proposal_fn=proposal)
    bundle = generator.generate(
        profile_id="demo",
        parent_id=None,
        base_contract=_base_contract(),
        experiences=[],
    )

    assert bundle.patch[0]["value"]["persona_id"] == "P2"
    assert bundle.policy["ucb_exploration_c"] == 1.4
