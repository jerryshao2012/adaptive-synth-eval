from __future__ import annotations

import hashlib
import json
import os
import re
import fcntl
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator


def _secret_safe_payload(value: Any, *, redact: bool = False) -> Any:
    if redact:
        if isinstance(value, dict):
            return {str(key): "<redacted>" for key in value}
        return "<redacted>"
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).lower()
            sensitive = (
                lowered == "auth"
                or "password" in lowered
                or "secret" in lowered
                or ("token" in lowered and lowered != "max_tokens")
                or ("api_key" in lowered and lowered != "api_key_env")
            )
            result[str(key)] = _secret_safe_payload(item, redact=sensitive)
        return result
    if isinstance(value, (list, tuple)):
        return [_secret_safe_payload(item) for item in value]
    return value


def artifact_fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        _secret_safe_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_signature_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


class ExperienceBuilder:
    def __init__(self, output_dir: str | Path, profile_id: str) -> None:
        self.output_dir = Path(output_dir)
        self.profile_id = profile_id
        self.root = self.output_dir / "learning" / profile_id
        self.ledger_path = self.root / "experience.jsonl"
        self.lock_path = self.root / ".experience.lock"

    def mine(self, run_dirs: Iterable[str | Path]) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._locked():
            return self._mine_locked(run_dirs)

    def _mine_locked(
        self, run_dirs: Iterable[str | Path]
    ) -> dict[str, Any]:
        existing = {
            str(record.get("run_id"))
            for record in self.read_records()
            if record.get("run_id")
        }
        records: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for raw_path in run_dirs:
            run_dir = Path(raw_path)
            run_id = run_dir.name
            if run_id in existing:
                skipped.append({"run_id": run_id, "reason": "already_mined"})
                continue
            try:
                record, reason = self._build_record(run_dir)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                record, reason = None, "corrupt_artifacts"
            if record is None:
                skipped.append({"run_id": run_id, "reason": reason})
                continue
            self._append_record(record)
            existing.add(run_id)
            records.append(record)
        return {
            "added": len(records),
            "records": records,
            "skipped": skipped,
            "ledger_path": str(self.ledger_path),
        }

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read_records(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def _build_record(
        self, run_dir: Path
    ) -> tuple[dict[str, Any] | None, str]:
        state = self._read_json(run_dir / "run_state.json")
        summary = self._read_json(run_dir / "run_summary.json")
        contract = self._read_json(run_dir / "contract.normalized.json")
        plan = self._read_json(run_dir / "run_plan.json")
        run_id = str(state.get("run_id") or summary.get("run_id") or run_dir.name)

        if state.get("mode") != "unified":
            return None, "not_unified"
        if state.get("status") != "completed":
            return None, "incomplete"
        if bool(summary.get("dry_run")):
            return None, "dry_run"
        suite = contract.get("suite")
        contract_synthetic = (
            bool(suite.get("synthetic_flag", True))
            if isinstance(suite, dict)
            else True
        )
        if not contract_synthetic:
            return None, "non_synthetic"
        if state.get("contract_fingerprint") != artifact_fingerprint(contract):
            return None, "contract_fingerprint_mismatch"
        if state.get("plan_fingerprint") != artifact_fingerprint(plan):
            return None, "plan_fingerprint_mismatch"

        turns = self._read_jsonl(run_dir / "turns.jsonl")
        if any(row.get("synthetic_flag") is False for row in turns):
            return None, "non_synthetic"
        scores = {
            (str(row.get("conversation_id")), int(row.get("turn_id") or 0)): row
            for row in self._read_jsonl(run_dir / "scores.jsonl")
        }
        scenario_types = {
            str(item.get("scenario_id")): str(
                item.get("scenario_type") or "unknown"
            )
            for catalog in (
                contract.get("scenario_catalog") or [],
                contract.get("adversarial_scenario_catalog") or [],
            )
            for item in catalog
            if isinstance(item, dict)
        }
        plan_seeds = {
            str(item.get("conversation_id")): int(
                item.get("seed", item.get("conversation_seed", 0)) or 0
            )
            for item in plan
            if isinstance(item, dict)
        }

        personas: Counter[str] = Counter()
        scenarios: Counter[str] = Counter()
        angles: Counter[str] = Counter()
        adversarial_conversation_ids: set[str] = set()
        failure_signatures: list[dict[str, Any]] = []
        judge_errors = 0
        target_fingerprint = artifact_fingerprint(contract.get("target") or {})

        for turn in turns:
            if turn.get("turn_type") != "adversarial":
                continue
            conversation_id = str(turn.get("conversation_id") or "")
            turn_id = int(turn.get("turn_id") or 0)
            adversarial_conversation_ids.add(conversation_id)
            metadata = turn.get("generation_metadata") or {}
            strategy = (
                metadata.get("strategy") or {}
                if isinstance(metadata, dict)
                else {}
            )
            scenario_id = str(
                metadata.get("adversarial_scenario_id")
                if isinstance(metadata, dict)
                else ""
            )
            scenario_type = scenario_types.get(scenario_id, "unknown")
            persona_id = str(turn.get("persona_id") or "unknown")
            attack_angle = normalize_signature_text(strategy.get("attack_angle"))
            sub_tactic = normalize_signature_text(strategy.get("sub_tactic"))
            personas[persona_id] += 1
            scenarios[scenario_type] += 1
            if attack_angle:
                angles[attack_angle] += 1

            score = scores.get((conversation_id, turn_id), {})
            if bool(score.get("judge_error")):
                judge_errors += 1
            if not bool(score.get("is_breach")):
                continue
            components = {
                "target_fingerprint": target_fingerprint,
                "scenario_type": scenario_type,
                "failure_type": normalize_signature_text(
                    score.get("failure_type")
                ),
                "attack_angle": attack_angle or "unknown",
                "sub_tactic": sub_tactic or "unknown",
            }
            failure_signatures.append(
                {
                    "signature": artifact_fingerprint(components),
                    "components": components,
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "seed": plan_seeds.get(conversation_id, 0),
                }
            )

        adversarial_turns = sum(personas.values())
        total_conversations = int(summary.get("total_conversations") or 0)
        total_tokens = self._summary_total_tokens(summary.get("tokens") or {})
        return (
            {
                "schema_version": 1,
                "profile_id": self.profile_id,
                "run_id": run_id,
                "run_dir": str(run_dir),
                "contract_fingerprint": str(state["contract_fingerprint"]),
                "plan_fingerprint": str(state["plan_fingerprint"]),
                "target_fingerprint": target_fingerprint,
                "total_conversations": total_conversations,
                "adversarial_conversations": len(
                    [item for item in adversarial_conversation_ids if item]
                ),
                "adversarial_turns": adversarial_turns,
                "failure_signatures": failure_signatures,
                "coverage": {
                    "personas": dict(sorted(personas.items())),
                    "scenarios": dict(sorted(scenarios.items())),
                    "angles": dict(sorted(angles.items())),
                },
                "judge_errors": judge_errors,
                "judge_error_rate": (
                    judge_errors / adversarial_turns if adversarial_turns else 0.0
                ),
                "total_tokens": total_tokens,
                "tokens_per_conversation": (
                    total_tokens / total_conversations
                    if total_conversations
                    else 0.0
                ),
            },
            "",
        )

    def _append_record(self, record: dict[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    @staticmethod
    def _summary_total_tokens(tokens: dict[str, Any]) -> int:
        if tokens.get("total_tokens") is not None:
            return int(tokens.get("total_tokens") or 0)
        return sum(
            int(tokens.get(key) or 0)
            for key in ("simulator_total_tokens", "chatbot_total_tokens")
        )
