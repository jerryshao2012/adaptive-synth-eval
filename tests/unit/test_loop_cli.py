import json
from pathlib import Path

from adaptive_synth_eval.cli import main
from adaptive_synth_eval.clients.llm import LLMResult


def test_cli_loop_init_creates_assets(tmp_path, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    (profiles_dir / "demo.yaml").write_text(
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

    exit_code = main(
        [
            "loop",
            "init",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["profile_id"] == "demo"
    assert Path(payload["state_path"]).exists()


def test_cli_loop_status_prints_persisted_state(tmp_path, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    (profiles_dir / "demo.yaml").write_text(
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

    main(
        [
            "loop",
            "init",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "loop",
            "status",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["profile_id"] == "demo"
    assert payload["status"] == "initialized"


def test_cli_loop_run_executes_target_and_updates_state(tmp_path, monkeypatch, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "simulation_suite": {
                    "suite_id": "test_suite",
                    "target_application": "hr_bot",
                    "run_mode": "synthetic_chat_history_generation",
                    "synthetic_flag": True,
                },
                "target": {"enabled": False},
                "time_window": {
                    "start_day": "2026-05-01",
                    "num_synthetic_days": 1,
                    "compressed_runtime_minutes": 5,
                },
                "persona_pool": [
                    {
                        "persona_id": "P001",
                        "role": "new_employee",
                        "location": "Canada",
                        "seniority": "junior",
                        "communication_style": "polite",
                        "hr_familiarity": "low",
                        "privacy_sensitivity": "medium",
                    }
                ],
                "scenario_catalog": [
                    {
                        "scenario_id": "S001",
                        "domain": "leave",
                        "intent": "understand_eligibility",
                        "expected_retrieval_topics": ["leave"],
                        "failure_injection": {"ambiguity": 0.2},
                        "success_criteria": {"answers_grounded_in_policy": True},
                    }
                ],
                "traffic_orchestration": {
                    "total_conversations": 1,
                    "conversation_turns": {"min": 3, "max": 3},
                    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
                },
                "output": {"base_dir": str(tmp_path / "target_outputs")},
            }
        ),
        encoding="utf-8",
    )
    (profiles_dir / "demo.yaml").write_text(
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

    captured = {}

    def _fake_run_simulation(*args, **kwargs):
        captured["dry_run"] = kwargs.get("dry_run")
        return {
            "run_id": "loop-run-1",
            "total_conversations": 1,
            "total_turns": 3,
            "errors": 0,
            "elapsed_seconds": 0.5,
            "output_dir": str(tmp_path / "target_outputs" / "runs" / "loop-run-1"),
        }

    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)
    monkeypatch.setattr(
        "adaptive_synth_eval.loop.planner.LLMClient.complete",
        lambda self, prompt: LLMResult(
            content=json.dumps(
                {
                    "ai_reasoning": "Planner selected the only safe target.",
                    "ai_hypothesis": "Dry run is enough for this baseline.",
                    "recommended_action": "Review the resulting summary.",
                    "selected_targets": [{"contract": str(contract)}],
                }
            )
            if "Choose the next safe target" in prompt
            else json.dumps(
                {
                    "key_finding": "No errors were reported.",
                    "ai_reflection": "The baseline remained stable.",
                    "follow_up_enabled": False,
                    "escalation_items": [],
                }
            ),
            raw={"provider": "mock"},
            error=None,
        ),
    )

    exit_code = main(
        [
            "loop",
            "run",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )

    captured_io = capsys.readouterr()
    payload = json.loads(captured_io.out)
    assert exit_code == 0
    assert captured["dry_run"] is True
    assert payload["profile_id"] == "demo"
    assert payload["targets_executed"] == 1

    state_path = tmp_path / "outputs" / "loops" / "state" / "demo.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    assert state["last_cycle"]["outcome"]["run_status"] == "completed"
    assert state["last_cycle"]["ai_reasoning"] == "Planner selected the only safe target."
    assert state["last_cycle"]["outcome"]["ai_reflection"] == "The baseline remained stable."
    assert state["recent_runs"][0]["run_id"] == "loop-run-1"
    assert "cycle completed" in (tmp_path / "outputs" / "loops" / "loop-run-log.md").read_text(encoding="utf-8")


def test_cli_loop_start_once_runs_single_cycle(tmp_path, monkeypatch, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "simulation_suite": {
                    "suite_id": "test_suite",
                    "target_application": "hr_bot",
                    "run_mode": "synthetic_chat_history_generation",
                    "synthetic_flag": True,
                },
                "target": {"enabled": False},
                "time_window": {
                    "start_day": "2026-05-01",
                    "num_synthetic_days": 1,
                    "compressed_runtime_minutes": 5,
                },
                "persona_pool": [
                    {
                        "persona_id": "P001",
                        "role": "new_employee",
                        "location": "Canada",
                        "seniority": "junior",
                        "communication_style": "polite",
                        "hr_familiarity": "low",
                        "privacy_sensitivity": "medium",
                    }
                ],
                "scenario_catalog": [
                    {
                        "scenario_id": "S001",
                        "domain": "leave",
                        "intent": "understand_eligibility",
                        "expected_retrieval_topics": ["leave"],
                        "failure_injection": {"ambiguity": 0.2},
                        "success_criteria": {"answers_grounded_in_policy": True},
                    }
                ],
                "traffic_orchestration": {
                    "total_conversations": 1,
                    "conversation_turns": {"min": 3, "max": 3},
                    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
                },
                "output": {"base_dir": str(tmp_path / "target_outputs")},
            }
        ),
        encoding="utf-8",
    )
    (profiles_dir / "demo.yaml").write_text(
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
    monkeypatch.setattr(
        "adaptive_synth_eval.cli.run_simulation",
        lambda *args, **kwargs: {
            "run_id": "loop-run-1",
            "total_conversations": 1,
            "total_turns": 3,
            "errors": 0,
            "elapsed_seconds": 0.5,
            "output_dir": str(tmp_path / "target_outputs" / "runs" / "loop-run-1"),
        },
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.loop.planner.LLMClient.complete",
        lambda self, prompt: LLMResult(
            content=json.dumps(
                {
                    "ai_reasoning": "Scheduler cycle selected the only target.",
                    "ai_hypothesis": "One pass is enough.",
                    "recommended_action": "Inspect the current outputs.",
                    "selected_targets": [{"contract": str(contract)}],
                }
            )
            if "Choose the next safe target" in prompt
            else json.dumps(
                {
                    "key_finding": "Cycle completed cleanly.",
                    "ai_reflection": "No regressions observed.",
                    "follow_up_enabled": False,
                    "escalation_items": [],
                }
            ),
            raw={"provider": "mock"},
            error=None,
        ),
    )

    exit_code = main(
        [
            "loop",
            "start",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
            "--once",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["completed_cycles"] == 1
    assert payload["cycle_summaries"][0]["profile_id"] == "demo"
    assert payload["interval_seconds"] == 3600.0
    state = json.loads((tmp_path / "outputs" / "loops" / "state" / "demo.json").read_text(encoding="utf-8"))
    assert state["last_cycle"]["ai_reasoning"] == "Scheduler cycle selected the only target."
    assert state["last_cycle"]["outcome"]["follow_up_enabled"] is False


def test_cli_loop_audit_reports_readiness(tmp_path, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    (profiles_dir / "demo.yaml").write_text(
        f"""
profile_id: demo
readiness_level: L2
cadence: hourly
targets:
  - contract: {contract}
checker_policy:
  max_retry_attempts: 2
  allow_auto_resume: true
denylist:
  - destructive
llm_config:
    provider: openai
    model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )

    main(
        [
            "loop",
            "init",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "loop",
            "audit",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["profile_id"] == "demo"
    assert payload["maker_checker_split"] is True
    assert payload["safeguards"]["max_retry_attempts"] == 2
    assert payload["files"]["STATE.md"] is True


def test_cli_loop_run_l2_checker_rejects_denylisted_target(tmp_path, monkeypatch, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "forbidden_contract.json"
    contract.write_text(
        json.dumps(
            {
                "simulation_suite": {
                    "suite_id": "test_suite",
                    "target_application": "hr_bot",
                    "run_mode": "synthetic_chat_history_generation",
                    "synthetic_flag": True,
                },
                "target": {"enabled": False},
                "time_window": {
                    "start_day": "2026-05-01",
                    "num_synthetic_days": 1,
                    "compressed_runtime_minutes": 5,
                },
                "persona_pool": [
                    {
                        "persona_id": "P001",
                        "role": "new_employee",
                        "location": "Canada",
                        "seniority": "junior",
                        "communication_style": "polite",
                        "hr_familiarity": "low",
                        "privacy_sensitivity": "medium",
                    }
                ],
                "scenario_catalog": [
                    {
                        "scenario_id": "S001",
                        "domain": "leave",
                        "intent": "understand_eligibility",
                        "expected_retrieval_topics": ["leave"],
                        "failure_injection": {"ambiguity": 0.2},
                        "success_criteria": {"answers_grounded_in_policy": True},
                    }
                ],
                "traffic_orchestration": {
                    "total_conversations": 1,
                    "conversation_turns": {"min": 3, "max": 3},
                    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
                },
                "output": {"base_dir": str(tmp_path / "target_outputs")},
            }
        ),
        encoding="utf-8",
    )
    (profiles_dir / "demo.yaml").write_text(
        f"""
profile_id: demo
readiness_level: L2
cadence: hourly
targets:
  - contract: {contract}
denylist:
  - forbidden
checker_policy:
  max_retry_attempts: 2
llm_config:
    provider: openai
    model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "adaptive_synth_eval.cli.run_simulation",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("target run should not execute")),
    )

    exit_code = main(
        [
            "loop",
            "run",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Checker rejected loop target" in captured.err

    state_path = tmp_path / "outputs" / "loops" / "state" / "demo.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["last_cycle"]["checker_decision"] == "rejected"


def test_cli_loop_pause_and_resume_toggle_kill_switch(tmp_path, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    (profiles_dir / "demo.yaml").write_text(
        f"""
profile_id: demo
readiness_level: L3
cadence: hourly
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

    main(["loop", "init", "--profile", "demo", "--profiles-dir", str(profiles_dir), "--output-dir",
          str(tmp_path / "outputs")])
    capsys.readouterr()

    exit_code = main(
        [
            "loop",
            "pause",
            "--profile",
            "demo",
            "--reason",
            "maintenance",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["paused"] is True
    assert payload["pause_reason"] == "maintenance"

    exit_code = main(
        [
            "loop",
            "resume",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["paused"] is False
    assert payload["pause_reason"] is None


def test_cli_loop_start_all_runs_profiles_in_priority_order(tmp_path, monkeypatch, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.yaml"
    contract.write_text("suite: demo\n", encoding="utf-8")
    (profiles_dir / "low.yaml").write_text(
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
    (profiles_dir / "high.yaml").write_text(
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
    seen = []
    monkeypatch.setattr(
        "adaptive_synth_eval.cli._run_loop_profile",
        lambda profile, **kwargs: seen.append(profile.profile_id) or {"profile_id": profile.profile_id},
    )

    exit_code = main(
        [
            "loop",
            "start",
            "--all",
            "--once",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert seen == ["high", "low"]
    assert payload["profiles"] == ["high", "low"]


def test_cli_loop_run_l3_auto_pauses_on_daily_run_cap(tmp_path, monkeypatch, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "simulation_suite": {"suite_id": "test_suite", "target_application": "hr_bot",
                                     "run_mode": "synthetic_chat_history_generation", "synthetic_flag": True},
                "target": {"enabled": False},
                "time_window": {"start_day": "2026-05-01", "num_synthetic_days": 1, "compressed_runtime_minutes": 5},
                "persona_pool": [
                    {"persona_id": "P001", "role": "new_employee", "location": "Canada", "seniority": "junior",
                     "communication_style": "polite", "hr_familiarity": "low", "privacy_sensitivity": "medium"}],
                "scenario_catalog": [{"scenario_id": "S001", "domain": "leave", "intent": "understand_eligibility",
                                      "expected_retrieval_topics": ["leave"], "failure_injection": {"ambiguity": 0.2},
                                      "success_criteria": {"answers_grounded_in_policy": True}}],
                "traffic_orchestration": {"total_conversations": 1, "conversation_turns": {"min": 3, "max": 3},
                                          "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}]},
                "output": {"base_dir": str(tmp_path / "target_outputs")},
            }
        ),
        encoding="utf-8",
    )
    (profiles_dir / "demo.yaml").write_text(
        f"""
profile_id: demo
readiness_level: L3
cadence: hourly
active_windows:
  - always
daily_run_cap: 1
targets:
  - contract: {contract}
llm_config:
    provider: openai
    model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )
    main(["loop", "init", "--profile", "demo", "--profiles-dir", str(profiles_dir), "--output-dir",
          str(tmp_path / "outputs")])
    capsys.readouterr()
    state_path = tmp_path / "outputs" / "loops" / "state" / "demo.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["budget"]["spent_today_runs"] = 1
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "adaptive_synth_eval.cli.run_simulation",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("target run should not execute")),
    )

    exit_code = main(
        [
            "loop",
            "run",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Daily run cap reached" in captured.err
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["paused"] is True


def test_cli_loop_run_l3_auto_pauses_after_checker_failures(tmp_path, monkeypatch, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    contract = tmp_path / "forbidden_contract.json"
    contract.write_text(
        json.dumps(
            {
                "simulation_suite": {"suite_id": "test_suite", "target_application": "hr_bot",
                                     "run_mode": "synthetic_chat_history_generation", "synthetic_flag": True},
                "target": {"enabled": False},
                "time_window": {"start_day": "2026-05-01", "num_synthetic_days": 1, "compressed_runtime_minutes": 5},
                "persona_pool": [
                    {"persona_id": "P001", "role": "new_employee", "location": "Canada", "seniority": "junior",
                     "communication_style": "polite", "hr_familiarity": "low", "privacy_sensitivity": "medium"}],
                "scenario_catalog": [{"scenario_id": "S001", "domain": "leave", "intent": "understand_eligibility",
                                      "expected_retrieval_topics": ["leave"], "failure_injection": {"ambiguity": 0.2},
                                      "success_criteria": {"answers_grounded_in_policy": True}}],
                "traffic_orchestration": {"total_conversations": 1, "conversation_turns": {"min": 3, "max": 3},
                                          "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}]},
                "output": {"base_dir": str(tmp_path / "target_outputs")},
            }
        ),
        encoding="utf-8",
    )
    (profiles_dir / "demo.yaml").write_text(
        f"""
profile_id: demo
readiness_level: L3
cadence: hourly
active_windows:
  - always
targets:
  - contract: {contract}
denylist:
  - forbidden
checker_policy:
  auto_pause_after_checker_failures: 1
llm_config:
    provider: openai
    model_name: gpt-4o-mini
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.cli.run_simulation",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("target run should not execute")),
    )

    exit_code = main(
        [
            "loop",
            "run",
            "--profile",
            "demo",
            "--profiles-dir",
            str(profiles_dir),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Checker rejected loop target" in captured.err
    state_path = tmp_path / "outputs" / "loops" / "state" / "demo.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["paused"] is True
    assert "Auto-paused after 1 consecutive checker failures" in state["pause_reason"]
