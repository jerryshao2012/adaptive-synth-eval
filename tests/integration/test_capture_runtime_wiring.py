"""Production persistence paths emit optional capture records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adaptive_synth_eval.artifacts.exporters import ArtifactWriter
from adaptive_synth_eval.capture.producers import (
    ChatHistoryProducerAdapter,
    PersonaMemoryProducerAdapter,
)
from adaptive_synth_eval.capture.runtime import capture_coordinator_from_env
from adaptive_synth_eval.capture.sinks import CaptureCoordinator
from adaptive_synth_eval.config.schemas import Persona
from adaptive_synth_eval.unified_eval.orchestrator.persona_memory_actor import (
    PersonaMemoryActor,
    PersonaMemoryDelta,
)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_artifact_writer_emits_capture_after_authoritative_row(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    coordinator = CaptureCoordinator(run_dir)
    writer = ArtifactWriter(
        tmp_path,
        run_id="run-1",
        capture_adapter=ChatHistoryProducerAdapter(coordinator),
    )
    row = {
        "conversation_id": "conversation-1",
        "turn_id": 3,
        "user_message": "hello",
        "bot_response": "hi",
    }

    writer.append_chat_history_rows([row])
    writer.append_chat_history_rows([row])

    assert len(_jsonl(run_dir / "chat_history.jsonl")) == 2
    skeletons = _jsonl(run_dir / "capture" / "skeleton.jsonl")
    assert len(skeletons) == 1
    assert skeletons[0]["buffer_locator"]


@pytest.mark.asyncio
async def test_persona_memory_actor_emits_capture_after_commit(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-1"
    coordinator = CaptureCoordinator(run_dir)
    persona = Persona(
        persona_id="P1",
        role="tester",
        location="Canada",
        seniority="senior",
        communication_style="direct",
        hr_familiarity="high",
        privacy_sensitivity="high",
    )
    actor = PersonaMemoryActor(
        persona=persona,
        markdown_path=run_dir / "personas" / "P1_memory.md",
        capture_adapter=PersonaMemoryProducerAdapter(coordinator),
    )
    await actor.start()
    await actor.commit(
        "conversation-1",
        1,
        PersonaMemoryDelta(preferences={"coverage": "family"}),
    )
    await actor.close()

    skeletons = _jsonl(run_dir / "capture" / "skeleton.jsonl")
    assert len(skeletons) == 1
    assert skeletons[0]["producer_id"] == "persona:P1"


def test_capture_runtime_is_opt_in_and_has_bounded_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASE_CAPTURE_ENABLED", raising=False)
    assert capture_coordinator_from_env(tmp_path) is None

    monkeypatch.setenv("ASE_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("ASE_CAPTURE_MAX_RECORDS_PER_PRODUCER", "7")
    coordinator = capture_coordinator_from_env(tmp_path)
    assert coordinator is not None
    assert coordinator.max_records_per_producer == 7
