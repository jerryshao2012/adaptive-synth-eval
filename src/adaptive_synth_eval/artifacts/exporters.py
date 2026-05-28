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
        ]
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
