from datetime import datetime, timezone
from unittest.mock import patch

from adaptive_synth_eval.clients.llm import LLMResult
from adaptive_synth_eval.loop.planner import LoopReasoner
from adaptive_synth_eval.loop.profiles import load_loop_profile
from adaptive_synth_eval.loop.scheduler import (
    LoopScheduler,
    MultiLoopCoordinator,
    cadence_to_interval_seconds,
    is_within_active_window,
)


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


def test_active_window_allows_expected_times(tmp_path):
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        f"""
profile_id: demo
readiness_level: L3
cadence: hourly
active_windows:
    - MON-FRI@08:00-18:00
targets:
    - contract: {contract}
llm_config:
    provider: openai
    model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )
    profile = load_loop_profile(str(profile_path))

    assert is_within_active_window(
        profile,
        now=datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc),
        state={},
    ) is True
    assert is_within_active_window(
        profile,
        now=datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc),
        state={},
    ) is False


def test_multi_loop_coordinator_honors_priority_order(tmp_path):
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    low_path = tmp_path / "low.yaml"
    low_path.write_text(
        f"""
profile_id: low
readiness_level: L3
cadence: hourly
priority: 50
active_windows:
    - always
targets:
    - contract: {contract}
llm_config:
    provider: openai
    model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )
    high_path = tmp_path / "high.yaml"
    high_path.write_text(
        f"""
profile_id: high
readiness_level: L3
cadence: hourly
priority: 10
active_windows:
    - always
targets:
    - contract: {contract}
llm_config:
    provider: openai
    model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )
    low = load_loop_profile(str(low_path))
    high = load_loop_profile(str(high_path))
    seen = []
    coordinator = MultiLoopCoordinator(
        sleep_fn=lambda _: (_ for _ in ()).throw(AssertionError("sleep should not run")),
        now_fn=lambda: datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc),
    )

    result = coordinator.run_profiles(
        [low, high],
        cycle_fn=lambda profile: seen.append(profile.profile_id) or {"profile_id": profile.profile_id},
        state_fn=lambda profile: {},
        once=True,
    )

    assert seen == ["high", "low"]
    assert result["profiles"] == ["high", "low"]
