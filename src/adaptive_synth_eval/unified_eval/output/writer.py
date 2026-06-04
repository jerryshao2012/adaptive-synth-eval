"""Unified artifact writer. Extends ASE's ArtifactWriter with adversarial-side files."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from adaptive_synth_eval.artifacts.exporters import ArtifactWriter


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration string."""
    if seconds <= 0:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.2f} seconds"
    elif seconds < 3600:
        return f"{seconds:.2f} seconds (~{seconds / 60:.2f} mins)"
    else:
        return f"{seconds:.2f} seconds (~{seconds / 3600:.2f} hours)"


class UnifiedArtifactWriter(ArtifactWriter):
    """Adds turn-level + adversarial-side artifacts under outputs/runs/<run_id>/.

    Standard ASE files (chat_history.{jsonl,csv}, scores.jsonl, run_summary.json,
    generation_report.md) are inherited.
    """

    def persona_memory_path(self, persona_id: str) -> Path:
        return self.run_dir / "personas" / f"{persona_id}_memory.md"

    def write_unified_summary(self, summary: dict) -> Path:
        return self.write_json("run_summary.json", summary)

    def write_attack_memory(self, memory_dict: dict) -> Path:
        return self.write_json("attack_memory.json", memory_dict)

    def write_adversarial_sessions(self, sessions: Iterable[dict]) -> Path:
        return self.write_jsonl("adversarial_sessions.jsonl", sessions)

    def write_failed_examples(self, rows: Iterable[dict]) -> Path:
        return self.write_jsonl("failed_examples.jsonl", rows)

    def write_unified_report(self, summary: dict) -> Path:
        lines = [
            "# Unified Eval Report",
            "",
            f"- Run ID: {summary.get('run_id')}",
            f"- Total conversations: {summary.get('total_conversations')}",
            f"- Total turns: {summary.get('total_turns')}",
            f"  - Synth turns: {summary.get('synth_turns', 0)}",
            f"  - Adversarial turns: {summary.get('adversarial_turns', 0)}",
            f"- Errors: {summary.get('errors', 0)}",
            f"- Dry run: {summary.get('dry_run', False)}",
            f"- Configured max concurrency: {summary.get('configured_max_concurrency')}",
            f"- Effective max concurrency: {summary.get('effective_max_concurrency')}",
            f"- Elapsed seconds: {summary.get('elapsed_seconds')}",
            "",
        ]

        # Time / Speed at Scale Projections
        scale = summary.get("scale_projections", {})
        if scale:
            lines.extend([
                "## Time / Speed to Generate at Scale",
                f"- **Conversations generated per second**: {scale.get('conversations_per_second')}",
                "",
                "| Projected Volume | Extrapolated Time |",
                "| :--- | :--- |",
                f"| 1,000 conversations | {_format_duration(scale.get('time_for_1k_conversations_seconds', 0.0))} |",
                f"| 10,000 conversations (Month at scale) | {_format_duration(scale.get('time_for_10k_conversations_seconds', 0.0))} |",
                f"| 100,000 conversations | {_format_duration(scale.get('time_for_100k_conversations_seconds', 0.0))} |",
                "",
            ])
            if scale.get("steady_state_conversations_per_second"):
                lines.extend([
                    "### Steady-State Projection",
                    f"- **Estimated conversations per second at configured concurrency**: {scale.get('steady_state_conversations_per_second')}",
                    "",
                    "| Projected Volume | Estimated Time |",
                    "| :--- | :--- |",
                    f"| 1,000 conversations | {_format_duration(scale.get('steady_state_time_for_1k_conversations_seconds', 0.0))} |",
                    f"| 10,000 conversations (Month at scale) | {_format_duration(scale.get('steady_state_time_for_10k_conversations_seconds', 0.0))} |",
                    f"| 100,000 conversations | {_format_duration(scale.get('steady_state_time_for_100k_conversations_seconds', 0.0))} |",
                    "",
                ])

        performance = summary.get("performance", {})
        if performance:
            lines.extend([
                "## Runtime Performance",
                f"- Target latency total: {_format_duration(performance.get('target_latency_total_seconds', 0.0))}",
                f"- Avg target latency per turn: {_format_duration(performance.get('avg_target_latency_per_turn_seconds', 0.0))}",
                f"- Max target latency per turn: {_format_duration(performance.get('max_target_latency_per_turn_seconds', 0.0))}",
                f"- Avg conversation elapsed: {_format_duration(performance.get('avg_conversation_elapsed_seconds', 0.0))}",
                f"- Max conversation elapsed: {_format_duration(performance.get('max_conversation_elapsed_seconds', 0.0))}",
                f"- Avg target latency per conversation: {_format_duration(performance.get('avg_target_latency_per_conversation_seconds', 0.0))}",
                "",
            ])

        # Token & Cost Projections
        tokens = summary.get("tokens", {})
        if tokens:
            avg_prompt = tokens.get("avg_prompt_tokens_per_convo", 0.0)
            avg_completion = tokens.get("avg_completion_tokens_per_convo", 0.0)

            def calc_cost(prompt_rate, completion_rate, multiplier):
                cost_per_convo = (avg_prompt * prompt_rate / 1_000_000) + (avg_completion * completion_rate / 1_000_000)
                return f"${cost_per_convo * multiplier:.2f}"

            cost_lightweight_1k = calc_cost(0.20, 0.40, 1000)
            cost_lightweight_10k = calc_cost(0.20, 0.40, 10000)
            cost_premium_1k = calc_cost(1.00, 5.00, 1000)
            cost_premium_10k = calc_cost(1.00, 5.00, 10000)
            cost_highend_1k = calc_cost(3.00, 15.00, 1000)
            cost_highend_10k = calc_cost(3.00, 15.00, 10000)

            lines.extend([
                "## Simulator Token Usage & Estimated Cost",
                "",
                "| Metric | Prompt Tokens | Completion Tokens | Total Tokens |",
                "| :--- | :--- | :--- | :--- |",
                f"| **Total Run Usage** | {int(tokens.get('simulator_prompt_tokens') or 0):,} | {int(tokens.get('simulator_completion_tokens') or 0):,} | {int(tokens.get('simulator_total_tokens') or 0):,} |",
                f"| **Average per Convo** | {tokens.get('avg_prompt_tokens_per_convo') or 0.0:,} | {tokens.get('avg_completion_tokens_per_convo') or 0.0:,} | {tokens.get('avg_total_tokens_per_convo') or 0.0:,} |",
                "",
                "### Cost Extrapolations (USD)",
                "*Note: Cost calculations are based on Simulator LLM token usage and the specified API pricing tiers.*",
                "",
                "| Model Pricing Tier | Cost per 1K Convos | Cost per 10K Convos (Month) |",
                "| :--- | :--- | :--- |",
                f"| **Lightweight (e.g., nova-micro-v1:0)**<br>*(Input: $0.20/1M, Output: $0.40/1M)* | {cost_lightweight_1k} | {cost_lightweight_10k} |",
                f"| **Premium (e.g., anthropic claude-haiku-4-5-20251001)**<br>*(Input: $1.00/1M, Output: $5.00/1M)* | {cost_premium_1k} | {cost_premium_10k} |",
                f"| **High-End (e.g., Claude 3.5 Sonnet)**<br>*(Input: $3.00/1M, Output: $15.00/1M)* | {cost_highend_1k} | {cost_highend_10k} |",
                "",
            ])

            # Chatbot Cost Projections
            avg_cb_prompt = tokens.get("avg_chatbot_prompt_tokens_per_convo", 0.0)
            avg_cb_completion = tokens.get("avg_chatbot_completion_tokens_per_convo", 0.0)

            def calc_cb_cost(prompt_rate, completion_rate, multiplier):
                cost_per_convo = (avg_cb_prompt * prompt_rate / 1_000_000) + (
                        avg_cb_completion * completion_rate / 1_000_000)
                return f"${cost_per_convo * multiplier:.2f}"

            cb_cost_lightweight_1k = calc_cb_cost(0.20, 0.40, 1000)
            cb_cost_lightweight_10k = calc_cb_cost(0.20, 0.40, 10000)
            cb_cost_premium_1k = calc_cb_cost(1.00, 5.00, 1000)
            cb_cost_premium_10k = calc_cb_cost(1.00, 5.00, 10000)
            cb_cost_highend_1k = calc_cb_cost(3.00, 15.00, 1000)
            cb_cost_highend_10k = calc_cb_cost(3.00, 15.00, 10000)

            lines.extend([
                "## Chatbot Token Usage & Estimated Cost",
                "",
                "| Metric | Prompt Tokens | Completion Tokens | Total Tokens |",
                "| :--- | :--- | :--- | :--- |",
                f"| **Total Run Usage** | {int(tokens.get('chatbot_prompt_tokens') or 0):,} | {int(tokens.get('chatbot_completion_tokens') or 0):,} | {int(tokens.get('chatbot_total_tokens') or 0):,} |",
                f"| **Average per Convo** | {tokens.get('avg_chatbot_prompt_tokens_per_convo') or 0.0:,} | {tokens.get('avg_chatbot_completion_tokens_per_convo') or 0.0:,} | {tokens.get('avg_chatbot_total_tokens_per_convo') or 0.0:,} |",
                "",
                "### Chatbot Cost Extrapolations (USD)",
                "*Note: Cost calculations are based on estimated Chatbot token usage and the specified API pricing tiers.*",
                "",
                "| Model Pricing Tier | Cost per 1K Convos | Cost per 10K Convos (Month) |",
                "| :--- | :--- | :--- |",
                f"| **Lightweight (e.g., nova-micro-v1:0)**<br>*(Input: $0.20/1M, Output: $0.40/1M)* | {cb_cost_lightweight_1k} | {cb_cost_lightweight_10k} |",
                f"| **Premium (e.g., anthropic claude-haiku-4-5-20251001)**<br>*(Input: $1.00/1M, Output: $5.00/1M)* | {cb_cost_premium_1k} | {cb_cost_premium_10k} |",
                f"| **High-End (e.g., Claude 3.5 Sonnet)**<br>*(Input: $3.00/1M, Output: $15.00/1M)* | {cb_cost_highend_1k} | {cb_cost_highend_10k} |",
                "",
            ])

        lines.extend([
            "## Adversarial summary",
            f"- Max failure_score: {summary.get('max_failure_score', 0)}",
            f"- Failures at/above threshold: {summary.get('failures_at_threshold', 0)}",
            f"- Near misses: {summary.get('near_misses', 0)}",
            "",
            "## Synth summary",
            f"- Mean safety_score: {summary.get('mean_safety_score')}",
            f"- Mean relevance_score: {summary.get('mean_relevance_score')}",
            f"- Mean groundedness_score: {summary.get('mean_groundedness_score')}",
        ])
        path = self.run_dir / "generation_report.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
