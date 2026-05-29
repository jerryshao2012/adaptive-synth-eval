from adaptive_synth_eval.cli import main


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
  "target_chatbot": {"enabled": false},
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
  "target_chatbot": {"enabled": false},
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
  "target_chatbot": {"enabled": false},
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
  "target_chatbot": {"enabled": false},
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
  "target_chatbot": {"enabled": false},
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
  "target_chatbot": {"enabled": false},
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
