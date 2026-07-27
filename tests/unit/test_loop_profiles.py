import json

import pytest

from adaptive_synth_eval.loop.profiles import LoopProfileError, load_loop_profile
from adaptive_synth_eval.loop.state_store import get_loop_status, initialize_loop_assets


def test_load_loop_profile_parses_checked_in_profile():
    profile = load_loop_profile("daily_triage")

    assert profile.profile_id == "daily_triage"
    assert profile.readiness_level == "L1"
    assert profile.targets[0].contract == "contracts/examples/chatbot_test_contract.yaml"
    assert profile.llm_config is not None
    assert profile.llm_config.provider == "azure_openai"


def test_load_loop_profile_rejects_invalid_readiness_level(tmp_path):
    profile_path = tmp_path / "bad.yaml"
    profile_path.write_text(
        """
profile_id: bad_profile
readiness_level: L4
cadence: hourly
targets:
  - contract: contracts/examples/chatbot_test_contract.yaml
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(LoopProfileError, match="readiness_level"):
        load_loop_profile(str(profile_path))


def test_initialize_loop_assets_persists_state_and_artifacts(tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    profile_path = profiles_dir / "demo.yaml"
    profile_path.write_text(
        f"""
profile_id: demo
readiness_level: L1
cadence: hourly
targets:
  - contract: {contract}
llm_config:
  provider: ollama
  model_name: mistral:latest
""".strip(),
        encoding="utf-8",
    )
    profile = load_loop_profile(str(profile_path))

    summary = initialize_loop_assets(profile, output_dir=tmp_path / "outputs")

    state_path = tmp_path / "outputs" / "loops" / "state" / "demo.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert summary["profile_id"] == "demo"
    assert state["status"] == "initialized"
    assert (tmp_path / "outputs" / "loops" / "STATE.md").exists()
    assert (tmp_path / "outputs" / "loops" / "loop-budget.md").exists()
    assert "[demo] initialized" in (tmp_path / "outputs" / "loops" / "loop-run-log.md").read_text(encoding="utf-8")

    persisted = get_loop_status(profile_ref="demo", output_dir=tmp_path / "outputs", profiles_dir=profiles_dir)
    assert persisted["profile_id"] == "demo"
    assert persisted["profile_path"] == str(profile.source_path)


def test_learning_profile_defaults_are_safe_and_human_gated(tmp_path):
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    profile_path = tmp_path / "learning.yaml"
    profile_path.write_text(
        f"""
profile_id: learning_demo
readiness_level: L2
cadence: hourly
targets:
  - contract: {contract}
learning:
  enabled: true
  validation_contracts:
    - {contract}
""".strip(),
        encoding="utf-8",
    )

    profile = load_loop_profile(str(profile_path))

    assert profile.learning.enabled is True
    assert profile.learning.evidence_source == "synthetic_only"
    assert profile.learning.min_new_runs == 3
    assert profile.learning.min_new_adversarial_conversations == 100
    assert profile.learning.candidate_kinds == ("policy", "persona", "scenario")
    assert profile.learning.require_human_approval is True
    assert profile.learning.tournament.initial_pairs == 20
    assert profile.learning.tournament.batch_pairs == 20
    assert profile.learning.tournament.max_pairs == 100


def test_learning_profile_requires_locked_validation_contracts(tmp_path):
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    profile_path = tmp_path / "learning.yaml"
    profile_path.write_text(
        f"""
profile_id: learning_demo
readiness_level: L2
cadence: hourly
targets:
  - contract: {contract}
learning:
  enabled: true
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(LoopProfileError, match="validation_contracts"):
        load_loop_profile(str(profile_path))


def test_learning_profile_rejects_non_synthetic_evidence(tmp_path):
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    profile_path = tmp_path / "learning.yaml"
    profile_path.write_text(
        f"""
profile_id: learning_demo
readiness_level: L2
cadence: hourly
targets:
  - contract: {contract}
learning:
  enabled: true
  evidence_source: all_monitoring
  validation_contracts:
    - {contract}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(LoopProfileError, match="synthetic_only"):
        load_loop_profile(str(profile_path))
