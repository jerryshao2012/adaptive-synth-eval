import json
from pathlib import Path

from adaptive_synth_eval.loop.policy import LoopPolicyEngine
from adaptive_synth_eval.loop.profiles import load_loop_profile
from adaptive_synth_eval.loop.verifier import LoopVerifier


def _write_l2_profile(tmp_path: Path, contract_path: Path) -> Path:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        f"""
profile_id: demo
readiness_level: L2
cadence: hourly
targets:
  - contract: {contract_path}
checker_policy:
  max_retry_attempts: 1
  allow_auto_resume: true
  safe_max_concurrency: 2
llm_config:
  provider: openai
  model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )
    return profile_path


def test_policy_plans_auto_resume_and_summary_regeneration(tmp_path):
    contract = tmp_path / "contract.json"
    contract.write_text("{}", encoding="utf-8")
    profile_path = _write_l2_profile(tmp_path, contract)
    profile = load_loop_profile(str(profile_path))
    policy = LoopPolicyEngine(profile)

    run_dir = tmp_path / "outputs" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "run_state.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "run_id": "r1",
                "completed_conversations": 1,
                "total_planned_conversations": 10,
            }
        ),
        encoding="utf-8",
    )

    plan = policy.plan_target(
        loop_state={"recent_runs": []},
        target={"contract": str(contract)},
        mode_name="unified",
        run_dir=run_dir,
        default_incomplete_run_action="abort",
        max_concurrency=8,
    )

    action_names = [action.action for action in plan.assisted_actions]
    assert plan.incomplete_run_action == "resume"
    assert "auto_resume_incomplete" in action_names
    assert "regenerate_missing_summary" in action_names
    assert plan.max_concurrency_override == 2


def test_verifier_rejects_retry_limit_breach(tmp_path):
    contract = tmp_path / "contract.json"
    contract.write_text("{}", encoding="utf-8")
    profile_path = _write_l2_profile(tmp_path, contract)
    profile = load_loop_profile(str(profile_path))

    policy = LoopPolicyEngine(profile)
    verifier = LoopVerifier(profile)
    target = {"contract": str(contract)}
    restart_plan = policy.plan_target(
        loop_state={
            "recent_runs": [
                {
                    "contract": str(contract),
                    "status": "completed_with_errors",
                }
            ]
        },
        target=target,
        mode_name="synth",
        run_dir=None,
        default_incomplete_run_action="abort",
        max_concurrency=None,
    )
    restart_actions = [action for action in restart_plan.assisted_actions if
                       action.action == "auto_restart_stale_failed"]
    assert restart_actions
    synthetic_plan = restart_plan.__class__(
        denied=False,
        deny_reason=None,
        incomplete_run_action="restart",
        max_concurrency_override=None,
        assisted_actions=restart_actions,
    )
    decision = verifier.verify_plan(
        synthetic_plan,
        loop_state={"assisted_action_attempts": {f"{contract}::auto_restart_stale_failed": 1}},
        target=target,
    )

    assert decision.verdict == "rejected"
    assert "auto_restart_stale_failed" in decision.rejected_actions
