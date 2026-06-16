from unittest.mock import patch

from adaptive_synth_eval.clients.llm import LLMResult
from adaptive_synth_eval.loop.planner import LoopReasoner
from adaptive_synth_eval.loop.profiles import load_loop_profile
from adaptive_synth_eval.loop.scheduler import LoopScheduler, cadence_to_interval_seconds


def test_cadence_to_interval_supports_repo_examples():
    assert cadence_to_interval_seconds("hourly") == 3600.0
    assert cadence_to_interval_seconds("daily") == 86400.0
    assert cadence_to_interval_seconds("*/2 * * * *") == 120.0
    assert cadence_to_interval_seconds("0 */6 * * *") == 21600.0
    assert cadence_to_interval_seconds("0 8 * * MON-FRI") == 86400.0


def test_loop_scheduler_runs_once_without_sleep():
    profile = load_loop_profile("daily_triage")
    scheduler = LoopScheduler(sleep_fn=lambda _: (_ for _ in ()).throw(AssertionError("sleep should not run")))
    calls = []

    result = scheduler.run_profile(profile, cycle_fn=lambda: calls.append("x") or {"ok": True}, once=True)

    assert calls == ["x"]
    assert result["completed_cycles"] == 1


def test_loop_reasoner_uses_llm_json_when_available():
    profile = load_loop_profile("daily_triage")
    reasoner = LoopReasoner(profile)
    response = LLMResult(
        content='{"ai_reasoning":"Focus on the demo target.","ai_hypothesis":"Dry-run remains sufficient.","recommended_action":"Run the checked-in target.","selected_targets":[{"contract":"contracts/examples/chatbot_test_contract.yaml"}]}',
        raw={"provider": "mock"},
        error=None,
    )

    with patch("adaptive_synth_eval.loop.planner.LLMClient.complete", return_value=response):
        decision = reasoner.plan_cycle({"recent_runs": []})

    assert decision.source == "llm_json"
    assert decision.selected_targets[0]["contract"] == "contracts/examples/chatbot_test_contract.yaml"
    assert "Focus on the demo target" in decision.ai_reasoning
