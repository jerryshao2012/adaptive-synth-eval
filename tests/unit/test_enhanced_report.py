#!/usr/bin/env python3
"""Quick test to verify enhanced stats in unified eval report."""

import tempfile

from adaptive_synth_eval.unified_eval.output.writer import UnifiedArtifactWriter


def test_unified_report_with_enhanced_stats():
    """Test that write_unified_report includes scale projections and token costs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = UnifiedArtifactWriter(tmpdir, run_id="test_run")

        summary = {
            "run_id": "test_run",
            "total_conversations": 10,
            "total_turns": 50,
            "synth_turns": 30,
            "adversarial_turns": 20,
            "errors": 0,
            "dry_run": False,
            "elapsed_seconds": 45.5,
            "max_failure_score": 2,
            "failures_at_threshold": 0,
            "near_misses": 3,
            "mean_safety_score": 0.85,
            "mean_relevance_score": 0.92,
            "mean_groundedness_score": 0.88,
            "scale_projections": {
                "conversations_per_second": 0.22,
                "time_for_1k_conversations_seconds": 4545.45,
                "time_for_10k_conversations_seconds": 45454.55,
                "time_for_100k_conversations_seconds": 454545.45,
            },
            "tokens": {
                "simulator_prompt_tokens": 50000,
                "simulator_completion_tokens": 30000,
                "simulator_total_tokens": 80000,
                "avg_prompt_tokens_per_convo": 5000.0,
                "avg_completion_tokens_per_convo": 3000.0,
                "avg_total_tokens_per_convo": 8000.0,
                "chatbot_prompt_tokens": 40000,
                "chatbot_completion_tokens": 20000,
                "chatbot_total_tokens": 60000,
                "avg_chatbot_prompt_tokens_per_convo": 4000.0,
                "avg_chatbot_completion_tokens_per_convo": 2000.0,
                "avg_chatbot_total_tokens_per_convo": 6000.0,
            }
        }

        report_path = writer.write_unified_report(summary)

        # Verify file was created
        assert report_path.exists(), f"Report file not created at {report_path}"

        # Read and verify content
        content = report_path.read_text()

        # Check for enhanced sections
        assert "## Time / Speed to Generate at Scale" in content, "Missing scale projections section"
        assert "**Conversations generated per second**" in content, "Missing conversations per second"
        assert "1,000 conversations" in content, "Missing 1K projection"
        assert "10,000 conversations (Month at scale)" in content, "Missing 10K projection"
        assert "100,000 conversations" in content, "Missing 100K projection"

        assert "## Simulator Token Usage & Estimated Cost" in content, "Missing token usage section"
        assert "## Chatbot Token Usage & Estimated Cost" in content, "Missing chatbot token usage section"
        assert "### Chatbot Cost Extrapolations (USD)" in content, "Missing chatbot cost extrapolations"
        assert "**Total Run Usage**" in content, "Missing total run usage"
        assert "**Average per Convo**" in content, "Missing average per convo"
        assert "### Cost Extrapolations (USD)" in content, "Missing cost extrapolations"
        assert "Lightweight (e.g., GPT-4o-mini)" in content, "Missing lightweight tier"
        assert "Premium (e.g., GPT-4o)" in content, "Missing premium tier"
        assert "High-End (e.g., Claude 3.5 Sonnet)" in content, "Missing high-end tier"

        print("✅ All enhanced stats sections present in unified report!")
        print(f"\nReport written to: {report_path}")
        print("\n--- Report Preview ---")
        print(content[:1000])
        print("...\n")


if __name__ == "__main__":
    test_unified_report_with_enhanced_stats()
