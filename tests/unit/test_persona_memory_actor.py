from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from adaptive_synth_eval.clients.llm import LLMResult
from adaptive_synth_eval.config.schemas import Persona, Scenario
from adaptive_synth_eval.generation.turns import PersonaMarkdownMemory, UserSimulator
from adaptive_synth_eval.unified_eval.orchestrator.persona_memory_actor import (
    PersonaMemoryActor,
    PersonaMemoryConflictError,
    PersonaMemoryDelta,
)


def _persona() -> Persona:
    return Persona(
        persona_id="P_ACTOR",
        role="tester",
        location="Canada",
        seniority="senior",
        communication_style="direct",
        hr_familiarity="high",
        privacy_sensitivity="low",
    )


@pytest.mark.asyncio
async def test_actor_merges_out_of_order_commits_by_plan_sequence(tmp_path: Path):
    markdown_path = tmp_path / "P_ACTOR_memory.md"
    actor = PersonaMemoryActor(persona=_persona(), markdown_path=markdown_path)
    await actor.start()

    await actor.commit(
        "conv_000002",
        2,
        PersonaMemoryDelta(
            demographics={"name": "Bob"},
            long_term_recall=("second summary",),
        ),
    )
    await actor.commit(
        "conv_000001",
        1,
        PersonaMemoryDelta(
            demographics={"name": "Alice"},
            long_term_recall=("first summary",),
        ),
    )

    snapshot = await actor.snapshot()
    await actor.close()

    assert snapshot.demographics["name"] == "Bob"
    assert snapshot.long_term_recall == ("first summary", "second summary")
    state = json.loads(markdown_path.with_suffix(".json").read_text())
    assert state["version"] == 1
    assert list(state["updates"]) == ["conv_000001", "conv_000002"]
    rendered = markdown_path.read_text()
    assert rendered.index("first summary") < rendered.index("second summary")


@pytest.mark.asyncio
async def test_actor_commit_is_idempotent_and_rejects_conflicting_duplicate(tmp_path: Path):
    actor = PersonaMemoryActor(
        persona=_persona(),
        markdown_path=tmp_path / "P_ACTOR_memory.md",
    )
    await actor.start()
    delta = PersonaMemoryDelta(preferences={"coverage": "family"})

    await actor.commit("conv_000001", 1, delta)
    await actor.commit("conv_000001", 1, delta)

    with pytest.raises(PersonaMemoryConflictError, match="conv_000001"):
        await actor.commit(
            "conv_000001",
            1,
            PersonaMemoryDelta(preferences={"coverage": "single"}),
        )
    await actor.close()


@pytest.mark.asyncio
async def test_failed_markdown_render_rolls_back_json_commit(tmp_path: Path, monkeypatch):
    markdown_path = tmp_path / "P_ACTOR_memory.md"
    actor = PersonaMemoryActor(persona=_persona(), markdown_path=markdown_path)
    await actor.start()
    original_write = actor._atomic_write
    fail_markdown_once = True

    def flaky_write(path: Path, content: str) -> None:
        nonlocal fail_markdown_once
        if path == markdown_path and fail_markdown_once:
            fail_markdown_once = False
            raise OSError("markdown disk failure")
        original_write(path, content)

    monkeypatch.setattr(actor, "_atomic_write", flaky_write)

    with pytest.raises(OSError, match="markdown disk failure"):
        await actor.commit(
            "conv_000001",
            1,
            PersonaMemoryDelta(long_term_recall=("must not partially commit",)),
        )
    await actor.close()

    state = json.loads(markdown_path.with_suffix(".json").read_text())
    assert state["updates"] == {}
    assert "must not partially commit" not in markdown_path.read_text()


@pytest.mark.asyncio
async def test_actor_imports_legacy_markdown_as_base_state(tmp_path: Path):
    markdown_path = tmp_path / "P_ACTOR_memory.md"
    legacy = PersonaMarkdownMemory(_persona().persona_id)
    legacy.demographics["name"] = "Legacy User"
    legacy.long_term_recall.append("legacy summary")
    legacy.save_to_file(markdown_path)

    actor = PersonaMemoryActor(persona=_persona(), markdown_path=markdown_path)
    await actor.start()
    snapshot = await actor.snapshot()
    await actor.close()

    assert snapshot.demographics["name"] == "Legacy User"
    assert snapshot.long_term_recall == ("legacy summary",)
    assert markdown_path.with_suffix(".json").exists()


@pytest.mark.asyncio
async def test_actor_resumes_from_json_source_of_truth(tmp_path: Path):
    markdown_path = tmp_path / "P_ACTOR_memory.md"
    first = PersonaMemoryActor(persona=_persona(), markdown_path=markdown_path)
    await first.start()
    delta = PersonaMemoryDelta(
        settings={"notifications": "email"},
        long_term_recall=("persisted summary",),
    )
    await first.commit("conv_000001", 1, delta)
    await first.close()

    # The Markdown view is compatibility output; resume must trust the JSON state.
    markdown_path.write_text("# stale compatibility view\n", encoding="utf-8")
    resumed = PersonaMemoryActor(persona=_persona(), markdown_path=markdown_path)
    await resumed.start()
    snapshot = await resumed.snapshot()
    await resumed.commit("conv_000001", 1, delta)
    await resumed.close()

    assert snapshot.settings["notifications"] == "email"
    assert snapshot.long_term_recall == ("persisted summary",)
    assert "persisted summary" in markdown_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_actor_keeps_every_durable_update_and_bounds_merged_memory(tmp_path: Path):
    actor = PersonaMemoryActor(
        persona=_persona(),
        markdown_path=tmp_path / "P_ACTOR_memory.md",
    )
    await actor.start()

    await asyncio.gather(*(
        actor.commit(
            f"conv_{sequence:06d}",
            sequence,
            PersonaMemoryDelta(
                preferences={f"preference_{sequence}": sequence},
                summary_notes=(f"note {sequence}",),
                long_term_recall=(f"summary {sequence}",),
            ),
        )
        for sequence in reversed(range(1, 33))
    ))

    snapshot = await actor.snapshot()
    await actor.close()

    assert snapshot.summary_notes == tuple(
        f"note {sequence}" for sequence in range(23, 33)
    )
    assert snapshot.long_term_recall == tuple(
        f"summary {sequence}" for sequence in range(13, 33)
    )
    assert snapshot.preferences == {
        f"preference_{sequence}": sequence for sequence in range(1, 33)
    }
    state = json.loads(actor.state_path.read_text(encoding="utf-8"))
    assert len(state["updates"]) == 32
    assert {
        update["delta"]["long_term_recall"][0]
        for update in state["updates"].values()
    } == {f"summary {sequence}" for sequence in range(1, 33)}


@pytest.mark.asyncio
async def test_snapshot_drives_conversation_local_memory_and_delta(tmp_path: Path):
    actor = PersonaMemoryActor(
        persona=_persona(),
        markdown_path=tmp_path / "P_ACTOR_memory.md",
    )
    await actor.start()
    initial = await actor.snapshot()
    simulator = UserSimulator(
        persona=_persona(),
        scenario=Scenario(scenario_id="S", domain="benefits", intent="enroll"),
        turn_count=1,
        seed=42,
        memory=initial.to_memory(_persona().persona_id),
    )

    with patch.object(simulator.llm_client, "complete") as complete:
        complete.return_value = LLMResult(
            content="Hi, my name is Jerry. I prefer family coverage.",
            raw={},
        )
        simulator.generate_turn(1)
    simulator.save_conversation_summary_to_long_term_recall()

    delta = PersonaMemoryDelta.between(initial, simulator.memory)
    await actor.commit("conv_000001", 1, delta)
    final = await actor.snapshot()
    await actor.close()

    assert final.demographics["name"] == "Jerry"
    assert final.preferences["stated_preference"] == "family coverage"
    assert len(final.long_term_recall) == 1
    assert final.summary_notes == ()
