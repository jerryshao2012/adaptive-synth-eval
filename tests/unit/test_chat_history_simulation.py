import asyncio
import csv
import json
from copy import deepcopy
from datetime import datetime

import pytest

from adaptive_synth_eval.clients.chatbot import ChatbotResponse
from adaptive_synth_eval.clients.llm import LLMResult
from adaptive_synth_eval.config.contract import ContractError, load_contract
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


def test_profiled_synth_run_propagates_timestamps_provenance_and_behavior(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    payload = build_synth_contract_payload(
        run_id="profiled_synth",
        total_conversations=4,
        turn_min=3,
        turn_max=3,
        mix=[
            {
                "recipe_id": "r1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            },
            {
                "recipe_id": "r2",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            },
        ],
    )
    payload["time_profile"] = {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 3,
                "conversation_mode": "support",
                "behavior_mode": "stressed",
                "recipe_weights": {"r1": 1},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "15:00",
                "traffic_weight": 1,
                "conversation_mode": "support",
                "behavior_mode": "toxic",
                "recipe_weights": {"r2": 1},
            },
        ]
    }
    path = tmp_path / "profiled_synth.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)
    target_metadata = []

    class Target:
        async def send_async(self, **kwargs):
            target_metadata.append(kwargs["metadata"])
            return ChatbotResponse.from_payload(
                {"response": "Here is a grounded answer."},
                latency_ms=1.0,
                status_code=200,
            )

        async def close_async(self):
            return None

    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.create_chatbot_client",
        lambda *args, **kwargs: Target(),
    )
    monkeypatch.setattr(
        "adaptive_synth_eval.generation.turns.LLMClient.complete",
        lambda *args, **kwargs: LLMResult(
            content="", raw={"mock": True}, error="llm_disabled"
        ),
    )

    summary = run_simulation(contract, dry_run=False)
    run_dir = tmp_path / "outputs" / "runs" / "profiled_synth"
    plan = json.loads((run_dir / "run_plan.json").read_text())
    chat = [
        json.loads(line)
        for line in (run_dir / "chat_history.jsonl").read_text().splitlines()
    ]
    conversations = [
        json.loads(line)
        for line in (run_dir / "conversations.jsonl").read_text().splitlines()
    ]
    scores = [
        json.loads(line) for line in (run_dir / "scores.jsonl").read_text().splitlines()
    ]

    assert [row["sequence"] for row in plan] == [1, 2, 3, 4]
    assert [row["conversation_id"] for row in conversations] == [
        "conv_000001",
        "conv_000002",
        "conv_000003",
        "conv_000004",
    ]
    provenance = {
        "sequence",
        "recipe_id",
        "synthetic_timestamp",
        "synthetic_slot",
        "profile_period_id",
        "profile_period_instance_id",
        "profile_period_start",
        "profile_period_end",
        "conversation_mode",
        "behavior_mode",
        "traffic_weight",
        "recipe_weights",
    }
    assert all(provenance <= row.keys() for row in plan)
    assert all(provenance | {"timestamp"} <= row.keys() for row in chat)
    assert all(provenance | {"timestamp"} <= row.keys() for row in conversations)
    assert all(provenance | {"timestamp"} <= row.keys() for row in scores)
    assert all(provenance | {"timestamp"} <= row.keys() for row in target_metadata)
    for conversation_id in {row["conversation_id"] for row in chat}:
        timestamps = [
            datetime.fromisoformat(row["timestamp"])
            for row in chat
            if row["conversation_id"] == conversation_id
        ]
        assert timestamps == sorted(timestamps)
        assert len(set(timestamps)) == 3
        period_end = datetime.fromisoformat(
            next(
                row["profile_period_end"]
                for row in chat
                if row["conversation_id"] == conversation_id
            )
        )
        assert timestamps[-1] <= period_end
    assert {row["generation_metadata"]["behavior_mode"] for row in chat} == {
        "stressed",
        "toxic",
    }
    assert summary["profile_counts"]["by_period"] == {"afternoon": 1, "morning": 3}
    with (run_dir / "chat_history.csv").open(newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert {"sequence", "timestamp", "profile_period_id"} <= set(csv_rows[0])
    assert csv_rows[0]["profile_period_id"] == "morning"


def test_profiled_synth_run_state_fingerprints_allow_same_plan_resume(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    payload = build_synth_contract_payload(
        run_id="profile_resume_same",
        total_conversations=2,
        mix=[
            {
                "recipe_id": "r1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            }
        ],
    )
    payload["time_profile"] = {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "15:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1},
            },
        ]
    }
    path = tmp_path / "profile_resume_same.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)
    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.build_profiled_run_plan",
        lambda contract, persona_id=None: [],
    )

    run_simulation(contract, dry_run=True)
    run_dir = tmp_path / "outputs" / "runs" / "profile_resume_same"
    first_state = json.loads((run_dir / "run_state.json").read_text())
    conversations_before = (run_dir / "conversations.jsonl").read_bytes()

    run_simulation(contract, dry_run=True, resume_incomplete=True)

    resumed_state = json.loads((run_dir / "run_state.json").read_text())
    assert first_state["version"] == resumed_state["version"] == 2
    assert len(resumed_state["contract_fingerprint"]) == 64
    assert len(resumed_state["plan_fingerprint"]) == 64
    assert resumed_state["contract_fingerprint"] == first_state["contract_fingerprint"]
    assert resumed_state["plan_fingerprint"] == first_state["plan_fingerprint"]
    assert (run_dir / "conversations.jsonl").read_bytes() == conversations_before


def test_profiled_synth_resume_without_checkpoint_creates_no_run_or_capture_dir(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    payload = build_synth_contract_payload(
        run_id="profile_resume_missing",
        total_conversations=2,
        mix=[
            {
                "recipe_id": "r1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            }
        ],
    )
    payload["time_profile"] = {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "15:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1},
            },
        ]
    }
    path = tmp_path / "profile_resume_missing.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)
    run_dir = tmp_path / "outputs" / "runs" / "profile_resume_missing"
    monkeypatch.setenv("ASE_CAPTURE_ENABLED", "true")
    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.build_profiled_run_plan",
        lambda contract, persona_id=None: [],
    )

    with pytest.raises(ContractError, match="without a run-state checkpoint"):
        run_simulation(contract, dry_run=True, resume_incomplete=True)

    assert not run_dir.exists()
    assert not (run_dir / "capture").exists()


@pytest.mark.parametrize("change", ["seed", "profile", "recipe"])
def test_profiled_synth_resume_rejects_changed_contract_before_artifact_mutation(
    tmp_path, monkeypatch, build_synth_contract_payload, change
):
    payload = build_synth_contract_payload(
        run_id=f"profile_resume_changed_{change}",
        total_conversations=2,
        mix=[
            {
                "recipe_id": "r1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            }
        ],
    )
    payload["time_profile"] = {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "15:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1},
            },
        ]
    }
    initial_path = tmp_path / f"profile_resume_changed_{change}.json"
    initial_path.write_text(json.dumps(payload))
    initial = load_contract(initial_path)
    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.build_profiled_run_plan",
        lambda contract, persona_id=None: [],
    )
    run_simulation(initial, dry_run=True)

    run_dir = tmp_path / "outputs" / "runs" / payload["output"]["run_id"]
    watched = {
        name: ((run_dir / name).read_bytes(), (run_dir / name).stat().st_mtime_ns)
        for name in (
            "run_state.json",
            "contract.normalized.json",
            "run_plan.json",
            "conversations.jsonl",
        )
    }
    changed = deepcopy(payload)
    if change == "seed":
        changed["traffic_orchestration"]["random_seed"] += 1
    elif change == "profile":
        changed["time_profile"]["windows"][0]["traffic_weight"] = 2
    else:
        changed["traffic_orchestration"]["mix"][0]["weight"] = 2
    changed_path = tmp_path / f"profile_resume_changed_{change}_new.json"
    changed_path.write_text(json.dumps(changed))
    monkeypatch.setenv("ASE_CAPTURE_ENABLED", "true")

    with pytest.raises(ContractError, match="effective contract differs"):
        run_simulation(
            load_contract(changed_path), dry_run=True, resume_incomplete=True
        )

    assert {
        name: ((run_dir / name).read_bytes(), (run_dir / name).stat().st_mtime_ns)
        for name in watched
    } == watched
    assert not (run_dir / "capture").exists()


def test_profiled_synth_resume_rejects_changed_full_plan_before_artifact_mutation(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    payload = build_synth_contract_payload(
        run_id="profile_resume_changed_plan",
        total_conversations=2,
        mix=[
            {
                "recipe_id": "r1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            }
        ],
    )
    payload["time_profile"] = {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "15:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1},
            },
        ]
    }
    path = tmp_path / "profile_resume_changed_plan.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)
    from adaptive_synth_eval.generation.traffic import build_profiled_run_plan

    changed_plan = build_profiled_run_plan(contract)
    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.build_profiled_run_plan",
        lambda contract, persona_id=None: [],
    )
    run_simulation(contract, dry_run=True)

    run_dir = tmp_path / "outputs" / "runs" / "profile_resume_changed_plan"
    watched = {
        name: (run_dir / name).read_bytes()
        for name in (
            "run_state.json",
            "contract.normalized.json",
            "run_plan.json",
            "conversations.jsonl",
        )
    }
    monkeypatch.setattr(
        "adaptive_synth_eval.engines.chat_history_simulation.build_profiled_run_plan",
        lambda contract, persona_id=None: changed_plan,
    )

    with pytest.raises(ContractError, match="full profiled run plan differs"):
        run_simulation(contract, dry_run=True, resume_incomplete=True)

    assert {name: (run_dir / name).read_bytes() for name in watched} == watched


def test_profiled_synth_resume_fingerprints_full_plan_before_completed_filtering(
    tmp_path, build_synth_contract_payload
):
    from adaptive_synth_eval.artifacts.fingerprints import fingerprint_payload
    from adaptive_synth_eval.artifacts.run_state import write_run_state
    from adaptive_synth_eval.config.contract import contract_to_dict
    from adaptive_synth_eval.engines.chat_history_simulation import (
        _serialize_synth_plan,
    )
    from adaptive_synth_eval.generation.traffic import build_profiled_run_plan

    personas = [
        {
            "persona_id": persona_id,
            "role": "employee",
            "location": "Canada",
            "seniority": "junior",
            "communication_style": "polite",
            "hr_familiarity": "low",
            "privacy_sensitivity": "medium",
        }
        for persona_id in ("P001", "P002")
    ]
    payload = build_synth_contract_payload(
        run_id="profile_resume_completed",
        total_conversations=4,
        persona_pool=personas,
        mix=[
            {
                "recipe_id": "r1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            },
            {
                "recipe_id": "r2",
                "persona_id": "P002",
                "scenario_id": "S001",
                "weight": 1,
            },
        ],
    )
    payload["time_profile"] = {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1, "r2": 1},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "15:00",
                "traffic_weight": 1,
                "recipe_weights": {"r1": 1, "r2": 1},
            },
        ]
    }
    path = tmp_path / "profile_resume_completed.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)
    full_plan = build_profiled_run_plan(contract)
    serialized_plan = _serialize_synth_plan(full_plan)
    normalized_contract = contract_to_dict(contract)
    run_dir = tmp_path / "outputs" / "runs" / "profile_resume_completed"
    write_run_state(
        run_dir,
        {
            "version": 2,
            "mode": "synth",
            "status": "in_progress",
            "run_id": "profile_resume_completed",
            "completed_conversation_ids": [item.conversation_id for item in full_plan],
            "metrics": {},
            "contract_fingerprint": fingerprint_payload(normalized_contract),
            "plan_fingerprint": fingerprint_payload(serialized_plan),
        },
    )

    summary = run_simulation(contract, dry_run=True, resume_incomplete=True)

    assert summary["total_conversations"] == 4
    watched = {
        name: (run_dir / name).read_bytes()
        for name in (
            "run_state.json",
            "contract.normalized.json",
            "run_plan.json",
            "conversations.jsonl",
        )
    }
    with pytest.raises(ContractError, match="full profiled run plan differs"):
        run_simulation(
            contract,
            dry_run=True,
            resume_incomplete=True,
            persona_filter="P001",
        )
    assert {name: (run_dir / name).read_bytes() for name in watched} == watched


def test_legacy_synth_artifacts_do_not_sprout_profile_fields(
    tmp_path, monkeypatch, write_synth_contract_json
):
    path, _ = write_synth_contract_json(
        run_id="legacy_no_profile", total_conversations=1, turn_min=3, turn_max=3
    )
    contract = load_contract(path)
    monkeypatch.setattr(
        "adaptive_synth_eval.generation.turns.LLMClient.complete",
        lambda *args, **kwargs: LLMResult(
            content="", raw={"mock": True}, error="llm_disabled"
        ),
    )

    run_simulation(contract, dry_run=True)
    run_dir = tmp_path / "outputs" / "runs" / "legacy_no_profile"
    artifact_names = (
        "run_plan.json",
        "chat_history.jsonl",
        "conversations.jsonl",
        "turns.jsonl",
        "scores.jsonl",
    )
    forbidden = {
        "timestamp",
        "recipe_id",
        "profile_period_id",
        "profile_period_instance_id",
        "behavior_mode",
    }
    for name in artifact_names:
        text = (run_dir / name).read_text()
        rows = (
            json.loads(text)
            if name.endswith(".json")
            else [json.loads(line) for line in text.splitlines()]
        )
        assert all(not (forbidden & row.keys()) for row in rows)

    with (run_dir / "chat_history.csv").open(newline="") as handle:
        assert next(csv.reader(handle)) == [
            "conversation_id",
            "session_id",
            "synthetic_day",
            "persona_id",
            "scenario_id",
            "turn_id",
            "user_message",
            "bot_response",
            "expected_retrieval_topics",
            "planned_failure_modes",
            "applied_failure_modes",
            "groundedness_score",
            "relevance_score",
            "safety_score",
            "clarification_score",
            "failure_mode",
            "latency_ms",
            "status_code",
            "error",
            "synthetic_flag",
            "retrieved_policy_ids",
            "generation_metadata",
        ]
    run_state = json.loads((run_dir / "run_state.json").read_text())
    assert run_state["version"] == 1
    assert "contract_fingerprint" not in run_state
    assert "plan_fingerprint" not in run_state


def test_profiled_synth_persona_filter_applies_before_recipe_selection(
    tmp_path, monkeypatch, build_synth_contract_payload
):
    personas = [
        {
            "persona_id": "P001",
            "role": "employee",
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
    ]
    payload = build_synth_contract_payload(
        run_id="profile_persona_filter",
        total_conversations=4,
        turn_min=3,
        turn_max=3,
        persona_pool=personas,
        mix=[
            {
                "recipe_id": "p1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            },
            {
                "recipe_id": "p2",
                "persona_id": "P002",
                "scenario_id": "S001",
                "weight": 99,
            },
        ],
    )
    payload["time_profile"] = {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 1,
                "recipe_weights": {"p1": 1, "p2": 1000},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "15:00",
                "traffic_weight": 1,
                "recipe_weights": {"p1": 1, "p2": 1000},
            },
        ]
    }
    path = tmp_path / "profile_persona_filter.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)
    monkeypatch.setattr(
        "adaptive_synth_eval.generation.turns.LLMClient.complete",
        lambda *args, **kwargs: LLMResult(content="", raw={}, error="llm_disabled"),
    )

    run_simulation(contract, dry_run=True, persona_filter="p001")

    plan_path = (
        tmp_path / "outputs" / "runs" / "profile_persona_filter" / "run_plan.json"
    )
    plan = json.loads(plan_path.read_text())
    assert len(plan) == 4
    assert {row["persona_id"] for row in plan} == {"P001"}
    assert {row["recipe_id"] for row in plan} == {"p1"}
    assert {row["profile_period_id"] for row in plan} == {
        "morning",
        "afternoon",
    }


def test_profiled_synth_persona_filter_rejects_window_without_eligible_recipe(
    tmp_path, build_synth_contract_payload
):
    payload = build_synth_contract_payload(
        total_conversations=4,
        num_synthetic_days=1,
        persona_pool=[
            {
                "persona_id": "P001",
                "role": "employee",
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
            {
                "recipe_id": "p1",
                "persona_id": "P001",
                "scenario_id": "S001",
                "weight": 1,
            },
            {
                "recipe_id": "p2",
                "persona_id": "P002",
                "scenario_id": "S001",
                "weight": 1,
            },
        ],
    )
    payload["time_profile"] = {
        "windows": [
            {
                "period_id": "morning",
                "start_time": "08:00",
                "end_time": "10:00",
                "traffic_weight": 1,
                "recipe_weights": {"p1": 1},
            },
            {
                "period_id": "afternoon",
                "start_time": "13:00",
                "end_time": "15:00",
                "traffic_weight": 1,
                "recipe_weights": {"p2": 1},
            },
        ]
    }
    path = tmp_path / "profile_missing_persona.json"
    path.write_text(json.dumps(payload))
    contract = load_contract(path)

    with pytest.raises(ContractError, match="afternoon.*eligible recipe.*P001"):
        run_simulation(contract, dry_run=True, persona_filter="P001")


def test_profile_and_legacy_csv_schemas_cannot_be_mixed_on_resume(tmp_path):
    from adaptive_synth_eval.artifacts.exporters import ArtifactWriter

    legacy = ArtifactWriter(tmp_path, run_id="schema", profile_enabled=False)
    legacy.append_chat_history_rows([], overwrite=True)
    profiled = ArtifactWriter(tmp_path, run_id="schema", profile_enabled=True)

    with pytest.raises(RuntimeError, match="CSV schema"):
        profiled.append_chat_history_rows([], overwrite=False)


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
