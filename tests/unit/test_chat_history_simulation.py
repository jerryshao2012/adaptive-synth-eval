import asyncio
import json
from copy import deepcopy

import pytest

from adaptive_synth_eval.clients.chatbot import ChatbotResponse
from adaptive_synth_eval.config.contract import load_contract
from adaptive_synth_eval.engines.chat_history_simulation import (
    _bounded_results,
    _effective_max_concurrency,
    run_simulation,
    run_simulation_async,
)


@pytest.mark.asyncio
async def test_bounded_results_stops_admission_and_drains_on_consumer_failure():
    admitted = asyncio.Event()
    release = asyncio.Event()
    started: list[int] = []
    finished: list[int] = []

    async def worker(item: int) -> int:
        started.append(item)
        if len(started) == 3:
            admitted.set()
        await admitted.wait()
        if item == 0:
            return item
        await release.wait()
        finished.append(item)
        return item

    async def consume() -> None:
        results = _bounded_results(
            list(range(8)),
            worker=worker,
            max_concurrency=3,
            can_admit=lambda: True,
        )
        try:
            async for item in results:
                if item == 0:
                    raise RuntimeError("artifact failed")
        finally:
            await results.aclose()

    run = asyncio.create_task(consume())
    await admitted.wait()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not run.done()
    assert started == [0, 1, 2]

    release.set()
    with pytest.raises(RuntimeError, match="artifact failed"):
        await run

    assert sorted(finished) == [1, 2]
    assert started == [0, 1, 2]


def test_run_simulation_dry_run_writes_expected_artifacts(
    tmp_path, write_synth_contract_json
):
    contract_path, _ = write_synth_contract_json(
        file_name="contract.json",
        run_id="run1",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
    )
    contract = load_contract(contract_path)

    summary = run_simulation(contract, dry_run=True)

    assert summary["total_conversations"] == 2
    assert summary["elapsed_seconds"] >= 0
    run_dir = tmp_path / "outputs" / "runs" / "run1"
    assert (run_dir / "generation_report.md").exists()

    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert run_summary["elapsed_seconds"] >= 0
    assert run_summary["configured_max_concurrency"] == 5
    assert run_summary["effective_max_concurrency"] == 5

    generation_report = (run_dir / "generation_report.md").read_text(encoding="utf-8")
    assert "Configured max concurrency:" in generation_report
    assert "Effective max concurrency:" in generation_report
    assert "Elapsed seconds:" in generation_report


def test_effective_max_concurrency_is_one_for_browser_chatbot(
    tmp_path, write_synth_contract_json
):
    contract_path, _ = write_synth_contract_json(
        file_name="contract.json",
        run_id="run1",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
        max_concurrency=5,
        target={
            "enabled": True,
            "mode": "browser",
            "browser": {
                "url": "https://chat.example.com",
                "input_selector": "textarea",
                "submit_selector": "button",
                "response_selector": ".bot-message",
            },
        },
    )
    contract = load_contract(contract_path)

    assert _effective_max_concurrency(contract) == 1


def test_browser_mode_summary_reports_effective_max_concurrency_one(
    tmp_path, write_synth_contract_json
):
    contract_path, _ = write_synth_contract_json(
        file_name="contract_browser.json",
        run_id="browser_run",
        total_conversations=1,
        turn_min=3,
        turn_max=3,
        max_concurrency=7,
        target={
            "enabled": True,
            "mode": "browser",
            "browser": {
                "url": "https://chat.example.com",
                "input_selector": "textarea",
                "submit_selector": "button",
                "response_selector": ".bot-message",
            },
        },
    )
    contract = load_contract(contract_path)

    summary = run_simulation(contract, dry_run=True)

    assert summary["configured_max_concurrency"] == 7
    assert summary["effective_max_concurrency"] == 1


def test_run_simulation_async_dry_run_writes_expected_artifacts(
    tmp_path, write_synth_contract_json
):
    contract_path, _ = write_synth_contract_json(
        file_name="contract_async.json",
        run_id="run_async",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
    )
    contract = load_contract(contract_path)

    summary = asyncio.run(run_simulation_async(contract, dry_run=True))

    assert summary["total_conversations"] == 2
    assert (
        tmp_path / "outputs" / "runs" / "run_async" / "generation_report.md"
    ).exists()


def test_run_simulation_with_output_conversations(tmp_path, write_synth_contract_json):
    contract_path, _ = write_synth_contract_json(
        file_name="contract.json",
        run_id="run1",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
    )
    contract = load_contract(contract_path)

    summary = run_simulation(contract, dry_run=True, output_conversations=True)

    assert summary["total_conversations"] == 2
    assert (tmp_path / "outputs" / "runs" / "run1" / "conversations.txt").exists()

    # Verify the file contains Persona/Bot labels
    content = (tmp_path / "outputs" / "runs" / "run1" / "conversations.txt").read_text(
        encoding="utf-8"
    )
    assert "Persona (Turn 1):" in content
    assert "Bot (Turn 1):" in content
    assert "Conversation ID:" in content


def test_run_simulation_realtime_chat_display_multi_persona(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    base_contract = build_synth_contract_payload(
        run_id="run1",
        total_conversations=1,
        turn_min=3,
        turn_max=3,
    )

    realtime_calls = []

    def _capture_realtime(*args, **kwargs):
        realtime_calls.append(kwargs)

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.display_persona_message",
        _capture_realtime,
    )

    single_path = tmp_path / "single_contract.json"
    single_path.write_text(json.dumps(base_contract))
    single_contract = load_contract(single_path)
    run_simulation(single_contract, dry_run=True, realtime_chat=True)
    assert len(realtime_calls) > 0

    realtime_calls.clear()
    multi_contract_payload = deepcopy(base_contract)
    multi_contract_payload["persona_pool"].append(
        {
            "persona_id": "P002",
            "role": "manager",
            "location": "Canada",
            "seniority": "senior",
            "communication_style": "direct",
            "hr_familiarity": "high",
            "privacy_sensitivity": "medium",
        }
    )
    multi_contract_payload["output"]["run_id"] = "run2"
    multi_path = tmp_path / "multi_contract.json"
    multi_path.write_text(json.dumps(multi_contract_payload))
    multi_contract = load_contract(multi_path)
    run_simulation(multi_contract, dry_run=True, realtime_chat=True)
    assert len(realtime_calls) > 0


def test_run_simulation_realtime_can_stop_early(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    contract_payload = build_synth_contract_payload(
        run_id="run_stop",
        total_conversations=1,
        turn_min=5,
        turn_max=5,
    )

    contract_path = tmp_path / "contract_stop.json"
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    class _FakeController:
        def __init__(self, *args, **kwargs):
            self.stop_requested = False
            self.behavior_mode = "default"
            self.active_persona_id = None

        def start(self):
            return True

        def stop(self):
            self.stop_requested = True

        def wait_if_paused(self):
            return not self.stop_requested

        def wait_for_turn_delay(self):
            # Simulate user stop right after first turn.
            self.stop_requested = True
            return False

        def set_active_persona(self, persona_id):
            self.active_persona_id = persona_id

        def notify_conversation_complete(self, persona_id):
            pass

        def get_behavior_for_persona(self, persona_id=None):
            return self.behavior_mode

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.RealtimeChatController",
        _FakeController,
    )

    summary = run_simulation(
        contract,
        dry_run=True,
        realtime_chat=True,
        interactive_realtime_controls=True,
    )

    assert summary["stopped_early"] is True
    assert summary["total_turns"] == 1


def test_run_simulation_stops_all_processes_when_target_chatbot_unavailable(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    contract_payload = build_synth_contract_payload(
        run_id="run_stop_all",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
        max_concurrency=1,
        target={"enabled": True, "endpoint": "http://chat.example.com"},
    )
    contract_path = tmp_path / "contract_stop_all.json"
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    calls = {"count": 0}

    class _FakeClient:
        async def send_async(self, **kwargs):
            calls["count"] += 1
            return ChatbotResponse.from_payload(
                {},
                latency_ms=None,
                status_code=0,
                error="Target chatbot unavailable: connection refused",
            )

        async def close_async(self):
            return None

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.create_chatbot_client",
        lambda *args, **kwargs: _FakeClient(),
    )

    summary = run_simulation(contract, dry_run=False)

    assert summary["stopped_early"] is True
    assert summary["total_turns"] == 0
    assert calls["count"] == 1


def test_run_simulation_stops_when_chatbot_returns_http200_with_error_body(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    """HTTP 200 with an error body (e.g. 403/CosmosDB key expired) must also stop all processes."""
    contract_payload = build_synth_contract_payload(
        run_id="run_stop_200_error",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
        max_concurrency=1,
        target={"enabled": True, "endpoint": "http://chat.example.com"},
    )
    contract_path = tmp_path / "contract_stop_200.json"
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    calls = {"count": 0}
    error_body = (
        "Error processing request: Status code: 403 Sub-status: 4018\n"
        '{"Errors":["Access to your account is currently revoked because the '
        'correspondent key is either disabled or expired."]}'
    )

    class _FakeClient:
        async def send_async(self, **kwargs):
            calls["count"] += 1
            # HTTP 200 but error content in the response body
            return ChatbotResponse.from_payload(
                {"response": error_body},
                latency_ms=605.0,
                status_code=200,
            )

        async def close_async(self):
            return None

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.create_chatbot_client",
        lambda *args, **kwargs: _FakeClient(),
    )

    summary = run_simulation(contract, dry_run=False)

    assert summary["stopped_early"] is True
    assert summary["total_turns"] == 0
    assert calls["count"] == 1


def test_realtime_controller_only_used_when_interactive_enabled(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    contract_payload = build_synth_contract_payload(
        run_id="run_non_interactive",
        total_conversations=1,
        turn_min=3,
        turn_max=3,
    )

    contract_path = tmp_path / "contract_non_interactive.json"
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    class _ShouldNotBeCreatedController:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "RealtimeChatController should not be created when interactive controls are disabled"
            )

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.RealtimeChatController",
        _ShouldNotBeCreatedController,
    )

    summary = run_simulation(
        contract,
        dry_run=True,
        realtime_chat=True,
        interactive_realtime_controls=False,
    )

    assert summary["stopped_early"] is False
    assert summary["total_turns"] == 3


def test_run_simulation_with_persona_filter(tmp_path, build_synth_contract_payload):
    import pytest

    from adaptive_synth_eval.config.contract import ContractError

    contract_path = tmp_path / "contract_filter.json"
    contract_payload = build_synth_contract_payload(
        run_id="run_filter",
        total_conversations=4,
        turn_min=3,
        turn_max=3,
        persona_pool=[
            {
                "persona_id": "P001",
                "role": "new_employee",
                "location": "Canada",
                "seniority": "junior",
                "communication_style": "polite",
                "hr_familiarity": "low",
                "privacy_sensitivity": "medium",
            },
            {
                "persona_id": "P002",
                "role": "manager",
                "location": "Canada",
                "seniority": "senior",
                "communication_style": "direct",
                "hr_familiarity": "high",
                "privacy_sensitivity": "medium",
            },
        ],
        mix=[
            {"persona_id": "P001", "scenario_id": "S001", "weight": 0.5},
            {"persona_id": "P002", "scenario_id": "S001", "weight": 0.5},
        ],
    )
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    # 1. Run simulation filtering by P002 (case-insensitive)
    summary = run_simulation(contract, dry_run=True, persona_filter="p002")

    # Check that conversations only for P002 were run
    turns_file = tmp_path / "outputs" / "runs" / "run_filter" / "turns.jsonl"
    assert turns_file.exists()
    lines = [
        json.loads(line) for line in turns_file.read_text(encoding="utf-8").splitlines()
    ]
    assert len(lines) > 0
    for turn in lines:
        assert turn["persona_id"] == "P002"

    # 2. Test invalid persona filter throws ContractError
    with pytest.raises(ContractError) as excinfo:
        run_simulation(contract, dry_run=True, persona_filter="P003")
    assert "not found in contract's persona pool" in str(excinfo.value)


def test_realtime_controller_seeded_with_filtered_persona_before_start(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    contract_path = tmp_path / "contract_filter_realtime.json"
    contract_payload = build_synth_contract_payload(
        run_id="run_filter_realtime",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
        persona_pool=[
            {
                "persona_id": "P001",
                "role": "new_employee",
                "location": "Canada",
                "seniority": "junior",
                "communication_style": "polite",
                "hr_familiarity": "low",
                "privacy_sensitivity": "medium",
            },
            {
                "persona_id": "P002",
                "role": "manager",
                "location": "Canada",
                "seniority": "senior",
                "communication_style": "direct",
                "hr_familiarity": "high",
                "privacy_sensitivity": "medium",
            },
        ],
        mix=[
            {"persona_id": "P001", "scenario_id": "S001", "weight": 0.5},
            {"persona_id": "P002", "scenario_id": "S001", "weight": 0.5},
        ],
    )
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    observed = {"seeded_before_start": False}

    class _FakeController:
        def __init__(self, *args, **kwargs):
            self.stop_requested = False
            self.behavior_mode = "default"
            self.active_persona_id = None

        def set_active_persona(self, persona_id):
            self.active_persona_id = persona_id

        def start(self):
            observed["seeded_before_start"] = self.active_persona_id == "P002"
            return True

        def stop(self):
            self.stop_requested = True

        def wait_if_paused(self):
            return not self.stop_requested

        def wait_for_turn_delay(self):
            return not self.stop_requested

        def notify_conversation_complete(self, persona_id):
            pass

        def get_behavior_for_persona(self, persona_id=None):
            return self.behavior_mode

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.RealtimeChatController",
        _FakeController,
    )

    run_simulation(
        contract,
        dry_run=True,
        realtime_chat=True,
        interactive_realtime_controls=True,
        persona_filter="P002",
    )

    assert observed["seeded_before_start"] is True


def test_realtime_controller_defaults_to_first_contract_persona_before_start(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    contract_path = tmp_path / "contract_first_persona_realtime.json"
    contract_payload = build_synth_contract_payload(
        run_id="run_first_persona_realtime",
        total_conversations=2,
        turn_min=3,
        turn_max=3,
        persona_pool=[
            {
                "persona_id": "P001",
                "role": "new_employee",
                "location": "Canada",
                "seniority": "junior",
                "communication_style": "polite",
                "hr_familiarity": "low",
                "privacy_sensitivity": "medium",
            },
            {
                "persona_id": "P002",
                "role": "manager",
                "location": "Canada",
                "seniority": "senior",
                "communication_style": "direct",
                "hr_familiarity": "high",
                "privacy_sensitivity": "medium",
            },
        ],
        mix=[
            {"persona_id": "P001", "scenario_id": "S001", "weight": 0.5},
            {"persona_id": "P002", "scenario_id": "S001", "weight": 0.5},
        ],
    )
    contract_path.write_text(json.dumps(contract_payload))
    contract = load_contract(contract_path)

    observed = {"seeded_before_start": False}

    class _FakeController:
        def __init__(self, *args, **kwargs):
            self.stop_requested = False
            self.behavior_mode = "default"
            self.active_persona_id = None

        def set_active_persona(self, persona_id):
            self.active_persona_id = persona_id

        def start(self):
            observed["seeded_before_start"] = self.active_persona_id == "P001"
            return True

        def stop(self):
            self.stop_requested = True

        def wait_if_paused(self):
            return not self.stop_requested

        def wait_for_turn_delay(self):
            return not self.stop_requested

        def notify_conversation_complete(self, persona_id):
            pass

        def get_behavior_for_persona(self, persona_id=None):
            return self.behavior_mode

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.RealtimeChatController",
        _FakeController,
    )

    run_simulation(
        contract,
        dry_run=True,
        realtime_chat=True,
        interactive_realtime_controls=True,
    )

    assert observed["seeded_before_start"] is True


def test_score_response_returns_nullable_scores_without_context():
    from adaptive_synth_eval.scoring.response_quality import score_response

    score = score_response(
        user_message="hello", bot_response="hi", expected_context=None
    )

    assert score.groundedness_score is None
    assert score.relevance_score is not None
    assert score.safety_score is not None
    assert score.tool_correctness is None


def test_detect_failure_mode_identifies_empty_response():
    from adaptive_synth_eval.scoring.failure_modes import detect_failure_mode

    assert detect_failure_mode("", error=None) == "empty_response"
    assert detect_failure_mode("ok", error="timeout") == "endpoint_error"
