import logging
from types import SimpleNamespace

from pathlib import Path

from adaptive_synth_eval.cli import main
from adaptive_synth_eval.unified_eval.config.contract import load_unified_contract

UNIFIED_EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "unified_evaluation_demo.yaml"


def test_cli_rejects_missing_contract(tmp_path, capsys):
    missing = tmp_path / "missing.yaml"

    exit_code = main(["validate-contract", str(missing)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Contract file not found" in captured.err


def test_cli_runs_dry_run_contract(tmp_path, capsys):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 2,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    exit_code = main(["run", "--contract", str(contract), "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Run complete" in captured.out
    assert list(output_dir.glob("runs/*/chat_history.jsonl"))


def test_cli_logs_elapsed_runtime_in_summary(tmp_path, monkeypatch, capsys):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    def _fake_run_simulation(*args, **kwargs):
        return {
            "run_id": "x",
            "total_conversations": 0,
            "total_turns": 0,
            "errors": 0,
            "dry_run": True,
            "stopped_early": False,
            "elapsed_seconds": 12.34,
            "output_dir": str(output_dir / "runs" / "x"),
        }

    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)

    exit_code = main(["run", "--contract", str(contract), "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Run complete" in captured.out


def test_cli_summarize_reads_run_summary(tmp_path, capsys):
    run_dir = tmp_path / "runs" / "abc"
    run_dir.mkdir(parents=True)
    (run_dir / "run_summary.json").write_text('{"run_id": "abc", "total_conversations": 2}')

    exit_code = main(["summarize", "--run-id", "abc", "--output-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"run_id": "abc"' in captured.out


def test_cli_runs_with_realtime_chat_option(tmp_path, capsys):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    exit_code = main(["run", "--contract", str(contract), "--dry-run", "--realtime-chat"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Run complete" in captured.out


def test_cli_runs_with_interactive_realtime_controls_option(tmp_path, capsys):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    exit_code = main(
        [
            "run",
            "--contract",
            str(contract),
            "--dry-run",
            "--realtime-chat",
            "--interactive-realtime-controls",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Run complete" in captured.out


def test_cli_realtime_chat_enables_interactive_controls_by_default(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    captured = {}

    def _fake_run_simulation(*args, **kwargs):
        captured["interactive_realtime_controls"] = kwargs["interactive_realtime_controls"]
        return {"run_id": "x", "total_conversations": 0, "total_turns": 0, "errors": 0}

    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)

    exit_code = main(["run", "--contract", str(contract), "--dry-run", "--realtime-chat"])

    assert exit_code == 0
    assert captured["interactive_realtime_controls"] is True


def test_cli_can_disable_interactive_controls_with_no_flag(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    captured = {}

    def _fake_run_simulation(*args, **kwargs):
        captured["interactive_realtime_controls"] = kwargs["interactive_realtime_controls"]
        return {"run_id": "x", "total_conversations": 0, "total_turns": 0, "errors": 0}

    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)

    exit_code = main(
        [
            "run",
            "--contract",
            str(contract),
            "--dry-run",
            "--realtime-chat",
            "--no-interactive-realtime-controls",
        ]
    )

    assert exit_code == 0
    assert captured["interactive_realtime_controls"] is False


def test_cli_disables_live_status_when_realtime_controls_enabled(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    captured = {}

    def _fake_live_status(*, title, enabled, realtime_interactive, runner):
        captured["enabled"] = enabled
        captured["realtime_interactive"] = realtime_interactive
        return runner(None, None)

    def _fake_run_simulation(*args, **kwargs):
        return {"run_id": "x", "total_conversations": 0, "total_turns": 0, "errors": 0}

    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("adaptive_synth_eval.cli._run_with_live_status", _fake_live_status)
    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)

    exit_code = main(["run", "--contract", str(contract), "--dry-run", "--realtime-chat"])

    assert exit_code == 0
    assert captured["enabled"] is True
    assert captured["realtime_interactive"] is True


def test_cli_realtime_no_controls_uses_non_interactive_renderer_mode(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    captured = {}

    def _fake_live_status(*, title, enabled, realtime_interactive, runner):
        captured["enabled"] = enabled
        captured["realtime_interactive"] = realtime_interactive
        return runner(None, None)

    def _fake_run_simulation(*args, **kwargs):
        return {"run_id": "x", "total_conversations": 0, "total_turns": 0, "errors": 0}

    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("adaptive_synth_eval.cli._run_with_live_status", _fake_live_status)
    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)

    exit_code = main(
        [
            "run",
            "--contract",
            str(contract),
            "--dry-run",
            "--realtime-chat",
            "--no-interactive-realtime-controls",
        ]
    )

    assert exit_code == 0
    assert captured["enabled"] is True
    assert captured["realtime_interactive"] is False


def test_cli_realtime_interactive_fails_fast_without_prompt_toolkit(tmp_path, monkeypatch, capsys):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "prompt_toolkit":
            raise ImportError("mocked missing prompt_toolkit")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    exit_code = main(["run", "--contract", str(contract), "--dry-run", "--realtime-chat"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "requires prompt_toolkit" in captured.err


def test_cli_runs_with_persona_option(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s"}
}
""".strip()
        % output_dir.as_posix()
    )

    captured = {}

    def _fake_run_simulation(*args, **kwargs):
        captured["persona_filter"] = kwargs.get("persona_filter")
        return {"run_id": "x", "total_conversations": 0, "total_turns": 0, "errors": 0}

    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)

    exit_code = main(["run", "--contract", str(contract), "--dry-run", "--persona", "P001"])

    assert exit_code == 0
    assert captured["persona_filter"] == "P001"


def test_cli_resume_incomplete_run_passes_resume_flag(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s", "run_id": "existing_run"}
}
""".strip()
        % output_dir.as_posix()
    )

    run_dir = output_dir / "runs" / "existing_run"
    run_dir.mkdir(parents=True)
    (run_dir / "run_state.json").write_text(
        '{"status":"in_progress","completed_conversations":1,"total_planned_conversations":5}',
        encoding="utf-8",
    )

    captured = {}

    def _fake_run_simulation(*args, **kwargs):
        captured["resume_incomplete"] = kwargs.get("resume_incomplete")
        return {"run_id": "existing_run", "total_conversations": 0, "total_turns": 0, "errors": 0}

    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)

    exit_code = main(
        [
            "run",
            "--contract",
            str(contract),
            "--dry-run",
            "--incomplete-run-action",
            "resume",
        ]
    )

    assert exit_code == 0
    assert captured["resume_incomplete"] is True


def test_cli_logs_pre_run_summary_before_realtime_controls(monkeypatch, caplog):
    contract = load_unified_contract(UNIFIED_EXAMPLE)

    def _fake_run(*args, **kwargs):
        logging.getLogger("adaptive_synth_eval.engines.realtime_controls").info(
            "Realtime controls: [h]elp, [s]tatus, [+] faster, [-] slower, [p]ause/resume, [q]uit, style <behavior>"
        )
        return {"run_id": "x", "total_conversations": 0, "total_turns": 0, "errors": 0}

    fake_mode = SimpleNamespace(load_contract=lambda _: contract, run=_fake_run)
    monkeypatch.setattr("adaptive_synth_eval.cli.get_mode", lambda _: fake_mode)

    with caplog.at_level("INFO"):
        exit_code = main(
            [
                "run",
                "--contract",
                str(UNIFIED_EXAMPLE),
                "--dry-run",
                "--realtime-chat",
                "--persona",
                "DEMO_P1",
            ]
        )

    assert exit_code == 0

    messages = [record.getMessage() for record in caplog.records]
    summary_index = next(i for i, message in enumerate(messages) if message.startswith("Run configuration:"))
    target_index = next(i for i, message in enumerate(messages) if message.startswith("Target:"))
    simulator_index = next(
        i for i, message in enumerate(messages)
        if message.startswith("Adaptive component user_simulator:")
    )
    controls_index = next(i for i, message in enumerate(messages) if message.startswith("Realtime controls:"))

    assert summary_index < controls_index
    assert target_index < controls_index
    assert simulator_index < controls_index
    expected_provider = (contract.llm_for("user_simulator").provider or "").lower()
    if expected_provider == "bedrock":
        assert "effective_runtime=mock synth adapter" in messages[simulator_index]
    else:
        assert "effective_runtime=mock synth adapter" not in messages[simulator_index]


def test_cli_restart_incomplete_run_cleans_existing_artifacts(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    output_dir = tmp_path / "outputs"
    contract.write_text(
        """
{
  "simulation_suite": {
    "suite_id": "test_suite",
    "target_application": "hr_bot",
    "run_mode": "synthetic_chat_history_generation",
    "synthetic_flag": true
  },
  "target": {"enabled": false},
  "time_window": {
    "start_day": "2026-05-01",
    "num_synthetic_days": 1,
    "compressed_runtime_minutes": 5
  },
  "persona_pool": [{
    "persona_id": "P001",
    "role": "new_employee",
    "location": "Canada",
    "seniority": "junior",
    "communication_style": "confused_but_polite",
    "hr_familiarity": "low",
    "privacy_sensitivity": "medium"
  }],
  "scenario_catalog": [{
    "scenario_id": "S001",
    "domain": "parental_leave_policy",
    "intent": "understand_eligibility",
    "expected_retrieval_topics": ["parental_leave"],
    "failure_injection": {"ambiguity": 0.5},
    "success_criteria": {"answers_grounded_in_policy": true}
  }],
  "traffic_orchestration": {
    "total_conversations": 1,
    "conversation_turns": {"min": 3, "max": 3},
    "mix": [{"persona_id": "P001", "scenario_id": "S001", "weight": 1.0}],
    "random_seed": 7
  },
  "output": {"base_dir": "%s", "run_id": "existing_run"}
}
""".strip()
        % output_dir.as_posix()
    )

    run_dir = output_dir / "runs" / "existing_run"
    run_dir.mkdir(parents=True)
    stale_file = run_dir / "stale.txt"
    stale_file.write_text("old", encoding="utf-8")
    (run_dir / "run_state.json").write_text(
        '{"status":"in_progress","completed_conversations":1,"total_planned_conversations":5}',
        encoding="utf-8",
    )

    captured = {}

    def _fake_run_simulation(*args, **kwargs):
        captured["stale_exists_before_run"] = stale_file.exists()
        captured["resume_incomplete"] = kwargs.get("resume_incomplete")
        return {"run_id": "existing_run", "total_conversations": 0, "total_turns": 0, "errors": 0}

    monkeypatch.setattr("adaptive_synth_eval.cli.run_simulation", _fake_run_simulation)

    exit_code = main(
        [
            "run",
            "--contract",
            str(contract),
            "--dry-run",
            "--incomplete-run-action",
            "restart",
        ]
    )

    assert exit_code == 0
    assert captured["stale_exists_before_run"] is False
    assert captured["resume_incomplete"] is False
