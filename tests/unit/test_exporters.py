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
        synthetic_flag=True,
    )

    writer.write_chat_history([record])

    assert (tmp_path / "runs" / "run1" / "chat_history.jsonl").exists()
    assert (tmp_path / "runs" / "run1" / "chat_history.csv").exists()
    assert "tool_correctness" not in (tmp_path / "runs" / "run1" / "chat_history.csv").read_text()
