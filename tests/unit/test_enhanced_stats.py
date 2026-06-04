from adaptive_synth_eval.artifacts.exporters import ArtifactWriter
from adaptive_synth_eval.clients.utils import count_tokens


def test_count_tokens():
    # Empty inputs
    assert count_tokens(None) == 0
    assert count_tokens("") == 0

    # Normal text
    text = "Hello, world! This is a simple test string."
    tokens = count_tokens(text)
    assert tokens > 0
    # Tiktoken or fallback should both give reasonable token counts
    assert isinstance(tokens, int)


def test_write_generation_report_with_enhanced_stats(tmp_path):
    writer = ArtifactWriter(tmp_path, run_id="test_run")

    summary = {
        "run_id": "test_run",
        "total_conversations": 10,
        "total_turns": 30,
        "errors": 0,
        "dry_run": True,
        "stopped_early": False,
        "elapsed_seconds": 5.0,
        "output_dir": str(writer.run_dir),
        "tokens": {
            "simulator_prompt_tokens": 1200,
            "simulator_completion_tokens": 300,
            "simulator_total_tokens": 1500,
            "avg_prompt_tokens_per_convo": 120.0,
            "avg_completion_tokens_per_convo": 30.0,
            "avg_total_tokens_per_convo": 150.0,
            "chatbot_prompt_tokens": 800,
            "chatbot_completion_tokens": 200,
            "chatbot_total_tokens": 1000,
            "avg_chatbot_prompt_tokens_per_convo": 80.0,
            "avg_chatbot_completion_tokens_per_convo": 20.0,
            "avg_chatbot_total_tokens_per_convo": 100.0,
        },
        "scale_projections": {
            "conversations_per_second": 2.0,
            "time_for_1k_conversations_seconds": 500.0,
            "time_for_10k_conversations_seconds": 5000.0,
            "time_for_100k_conversations_seconds": 50000.0,
        },
        "production_realism": {
            "mix_realism": [
                {
                    "mix": "P001 + S001",
                    "target_pct": 50.0,
                    "actual_pct": 60.0,
                    "actual_count": 6,
                }
            ],
            "persona_realism": [
                {
                    "persona_id": "P001",
                    "target_pct": 50.0,
                    "actual_pct": 60.0,
                    "actual_count": 6,
                }
            ],
            "scenario_realism": [
                {
                    "scenario_id": "S001",
                    "target_pct": 50.0,
                    "actual_pct": 60.0,
                    "actual_count": 6,
                }
            ],
            "temporal_realism": [
                {
                    "day": 1,
                    "target_pct": 100.0,
                    "actual_pct": 100.0,
                    "actual_count": 10,
                }
            ]
        }
    }

    report_path = writer.write_generation_report(summary)
    assert report_path.exists()

    report_content = report_path.read_text(encoding="utf-8")
    assert "## Time / Speed to Generate at Scale" in report_content
    assert "## Simulator Token Usage & Estimated Cost" in report_content
    assert "## Chatbot Token Usage & Estimated Cost" in report_content
    assert "### Chatbot Cost Extrapolations (USD)" in report_content
    assert "## Production Realism Analysis" in report_content
    assert "Lightweight (e.g., nova-micro-v1:0)" in report_content
    assert "P001 + S001" in report_content
    assert "P001" in report_content
    assert "S001" in report_content
    assert "Day 1" in report_content
