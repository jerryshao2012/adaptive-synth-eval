from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from adaptive_synth_eval.artifacts.schemas import ChatHistoryRecord


class ArtifactWriter:
    def __init__(self, base_dir: str | Path, *, run_id: str):
        self.base_dir = Path(base_dir)
        self.run_id = run_id
        self.run_dir = self.base_dir / "runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, payload) -> Path:
        path = self.run_dir / name
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        return path

    def write_jsonl(self, name: str, rows: Iterable[dict]) -> Path:
        path = self.run_dir / name
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, default=str) + "\n")
        return path

    def write_chat_history(self, records: list[ChatHistoryRecord]) -> None:
        rows = [record.to_dict() for record in records]
        self.write_jsonl("chat_history.jsonl", rows)
        self._write_csv("chat_history.csv", rows)

    def write_generation_report(self, summary: dict) -> Path:
        lines = [
            "# Synthetic Chat Generation Report",
            "",
            f"- Run ID: {summary.get('run_id')}",
            f"- Total conversations: {summary.get('total_conversations')}",
            f"- Total turns: {summary.get('total_turns')}",
            f"- Errors: {summary.get('errors')}",
            f"- Dry run: {summary.get('dry_run')}",
            f"- Elapsed seconds: {summary.get('elapsed_seconds')}",
            "",
        ]

        def format_duration(seconds: float) -> str:
            if seconds <= 0:
                return "N/A"
            if seconds < 60:
                return f"{seconds:.2f} seconds"
            elif seconds < 3600:
                return f"{seconds:.2f} seconds (~{seconds / 60:.2f} mins)"
            else:
                return f"{seconds:.2f} seconds (~{seconds / 3600:.2f} hours)"

        # Time / Speed at Scale Projections
        scale = summary.get("scale_projections", {})
        if scale:
            lines.extend([
                "## Time / Speed to Generate at Scale",
                f"- **Conversations generated per second**: {scale.get('conversations_per_second')}",
                "",
                "| Projected Volume | Extrapolated Time |",
                "| :--- | :--- |",
                f"| 1,000 conversations | {format_duration(scale.get('time_for_1k_conversations_seconds', 0.0))} |",
                f"| 10,000 conversations (Month at scale) | {format_duration(scale.get('time_for_10k_conversations_seconds', 0.0))} |",
                f"| 100,000 conversations | {format_duration(scale.get('time_for_100k_conversations_seconds', 0.0))} |",
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

            cost_lightweight_1k = calc_cost(0.15, 0.60, 1000)
            cost_lightweight_10k = calc_cost(0.15, 0.60, 10000)
            cost_premium_1k = calc_cost(2.50, 10.00, 1000)
            cost_premium_10k = calc_cost(2.50, 10.00, 10000)
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
                f"| **Lightweight (e.g., GPT-4o-mini)**<br>*(Input: $0.15/1M, Output: $0.60/1M)* | {cost_lightweight_1k} | {cost_lightweight_10k} |",
                f"| **Premium (e.g., GPT-4o)**<br>*(Input: $2.50/1M, Output: $10.00/1M)* | {cost_premium_1k} | {cost_premium_10k} |",
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

            cb_cost_lightweight_1k = calc_cb_cost(0.15, 0.60, 1000)
            cb_cost_lightweight_10k = calc_cb_cost(0.15, 0.60, 10000)
            cb_cost_premium_1k = calc_cb_cost(2.50, 10.00, 1000)
            cb_cost_premium_10k = calc_cb_cost(2.50, 10.00, 10000)
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
                f"| **Lightweight (e.g., GPT-4o-mini)**<br>*(Input: $0.15/1M, Output: $0.60/1M)* | {cb_cost_lightweight_1k} | {cb_cost_lightweight_10k} |",
                f"| **Premium (e.g., GPT-4o)**<br>*(Input: $2.50/1M, Output: $10.00/1M)* | {cb_cost_premium_1k} | {cb_cost_premium_10k} |",
                f"| **High-End (e.g., Claude 3.5 Sonnet)**<br>*(Input: $3.00/1M, Output: $15.00/1M)* | {cb_cost_highend_1k} | {cb_cost_highend_10k} |",
                "",
            ])

        # Production Realism Analysis
        realism = summary.get("production_realism", {})
        if realism:
            lines.extend(["## Production Realism Analysis", ""])

            # Persona Realism Table
            lines.extend([
                "### Persona Distribution Realism",
                "",
                "| Persona ID | Target % | Actual % | Actual Count |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for p in realism.get("persona_realism", []):
                lines.append(
                    f"| {p.get('persona_id')} | {p.get('target_pct')}% | {p.get('actual_pct')}% | {p.get('actual_count')} |")
            lines.append("")

            # Scenario Realism Table
            lines.extend([
                "### Scenario Distribution Realism",
                "",
                "| Scenario ID | Target % | Actual % | Actual Count |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for s in realism.get("scenario_realism", []):
                lines.append(
                    f"| {s.get('scenario_id')} | {s.get('target_pct')}% | {s.get('actual_pct')}% | {s.get('actual_count')} |")
            lines.append("")

            # Mix Realism Table
            lines.extend([
                "### Persona-Scenario Mix Realism",
                "",
                "| Mix | Target % | Actual % | Actual Count |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for m in realism.get("mix_realism", []):
                lines.append(
                    f"| {m.get('mix')} | {m.get('target_pct')}% | {m.get('actual_pct')}% | {m.get('actual_count')} |")
            lines.append("")

            # Temporal Realism Table
            lines.extend([
                "### Temporal (Daily) Distribution Realism",
                "",
                "| Synthetic Day | Target % | Actual % | Actual Count |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for t in realism.get("temporal_realism", []):
                lines.append(
                    f"| Day {t.get('day')} | {t.get('target_pct')}% | {t.get('actual_pct')}% | {t.get('actual_count')} |")
            lines.append("")

        path = self.run_dir / "generation_report.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def write_conversations_txt(self, records: list[ChatHistoryRecord]) -> Path:
        """Write conversations in human-readable format with Persona/Bot labels.

        Groups turns by conversation_id and formats them as a dialogue.
        """
        path = self.run_dir / "conversations.txt"

        # Group records by conversation_id
        conversations = {}
        for record in records:
            if record.conversation_id not in conversations:
                conversations[record.conversation_id] = []
            conversations[record.conversation_id].append(record)

        with path.open("w", encoding="utf-8") as handle:
            for conv_id in sorted(conversations.keys()):
                turns = conversations[conv_id]
                # Sort turns by turn_id
                turns.sort(key=lambda r: r.turn_id)

                handle.write(f"{'=' * 80}\n")
                handle.write(f"Conversation ID: {conv_id}\n")
                handle.write(f"Session ID: {turns[0].session_id}\n")
                handle.write(f"Persona: {turns[0].persona_id}\n")
                handle.write(f"Scenario: {turns[0].scenario_id}\n")
                handle.write(f"Synthetic Day: {turns[0].synthetic_day}\n")
                handle.write(f"{'=' * 80}\n\n")

                for turn in turns:
                    handle.write(f"Persona (Turn {turn.turn_id}):\n{turn.user_message}\n\n")
                    handle.write(f"Bot (Turn {turn.turn_id}):\n{turn.bot_response}\n\n")

                    if turn.error:
                        handle.write(f"[ERROR: {turn.error}]\n\n")

                    handle.write(f"---\n\n")

                handle.write(f"\n{'=' * 80}\n\n\n")

        return path

    def _write_csv(self, name: str, rows: list[dict]) -> Path:
        path = self.run_dir / name
        fieldnames = [
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
            "error",
            "synthetic_flag",
            "retrieved_policy_ids",
            "generation_metadata",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path
