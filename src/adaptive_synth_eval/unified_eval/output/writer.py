"""Unified artifact writer. Extends ASE's ArtifactWriter with adversarial-side files."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from adaptive_synth_eval.artifacts.exporters import ArtifactWriter


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
            "",
            "## Adversarial summary",
            f"- Max failure_score: {summary.get('max_failure_score', 0)}",
            f"- Failures at/above threshold: {summary.get('failures_at_threshold', 0)}",
            f"- Near misses: {summary.get('near_misses', 0)}",
            "",
            "## Synth summary",
            f"- Mean safety_score: {summary.get('mean_safety_score')}",
            f"- Mean relevance_score: {summary.get('mean_relevance_score')}",
            f"- Mean groundedness_score: {summary.get('mean_groundedness_score')}",
        ]
        path = self.run_dir / "generation_report.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
