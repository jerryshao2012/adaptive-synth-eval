from adaptive_synth_eval.clients.llm import LLMResult
from adaptive_synth_eval.loop.planner import LoopReasoner
from adaptive_synth_eval.loop.profiles import load_loop_profile


def test_loop_reasoner_falls_back_without_llm_config(tmp_path):
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        f"""
profile_id: demo
readiness_level: L1
cadence: hourly
targets:
  - contract: {contract}
""".strip(),
        encoding="utf-8",
    )
    profile = load_loop_profile(str(profile_path))

    reasoner = LoopReasoner(profile)
    plan = reasoner.plan_cycle(None)

    assert plan.source == "fallback"
    assert plan.selected_targets[0]["contract"] == str(contract)


def test_loop_reasoner_reflection_uses_llm_json(tmp_path, monkeypatch):
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        f"""
profile_id: demo
readiness_level: L1
cadence: hourly
targets:
  - contract: {contract}
llm_config:
  provider: openai
  model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )
    profile = load_loop_profile(str(profile_path))
    reasoner = LoopReasoner(profile)

    monkeypatch.setattr(
        "adaptive_synth_eval.loop.planner.LLMClient.complete",
        lambda self, prompt: LLMResult(
            content='{"key_finding":"Stable baseline","ai_reflection":"No regression indicators.","follow_up_enabled":false,"escalation_items":[]}',
            raw={"provider": "mock"},
            error=None,
        ),
    )

    reflection = reasoner.reflect_on_cycle(None, [{"errors": 0}], reasoner._fallback_plan(None))

    assert reflection.source == "llm_json"
    assert reflection.key_finding == "Stable baseline"
    assert reflection.ai_reflection == "No regression indicators."
