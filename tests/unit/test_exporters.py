import json
from datetime import date

from adaptive_synth_eval.artifacts.exporters import ArtifactWriter
from adaptive_synth_eval.artifacts.schemas import ChatHistoryRecord


def test_artifact_writer_writes_chat_history_jsonl_and_csv(tmp_path):
    writer = ArtifactWriter(tmp_path, run_id="run1")
    record = ChatHistoryRecord(
        conversation_id="c1",
        session_id="s1",
        synthetic_day=date(2026, 5, 1),
        persona_id="P001",
        scenario_id="S001",
        turn_id=1,
        user_message="hello",
        bot_response="hi",
        expected_retrieval_topics=["policy"],
        planned_failure_modes=[],
        applied_failure_modes=[],
        reference_context="Policy section 4 applies.",
        reference_answer="The employee is eligible.",
        status_code=207,
        synthetic_flag=True,
    )

    writer.write_chat_history([record])

    assert (tmp_path / "runs" / "run1" / "chat_history.jsonl").exists()
    assert (tmp_path / "runs" / "run1" / "chat_history.csv").exists()
    assert "tool_correctness" not in (tmp_path / "runs" / "run1" / "chat_history.csv").read_text()
    row = json.loads(
        (tmp_path / "runs" / "run1" / "chat_history.jsonl").read_text(encoding="utf-8")
    )
    assert row["reference_context"] == "Policy section 4 applies."
    assert row["reference_answer"] == "The employee is eligible."
    assert row["status_code"] == 207
    assert "207" in (
        tmp_path / "runs" / "run1" / "chat_history.csv"
    ).read_text()


def test_chat_history_reference_fields_do_not_shift_existing_positional_arguments():
    record = ChatHistoryRecord(
        "c1", "s1", date(2026, 5, 1), "P001", "S001", 1,
        "hello", "hi", ["policy"], [], [], 0.9,
    )

    assert record.groundedness_score == 0.9
    assert record.reference_context is None
    assert record.reference_answer is None
