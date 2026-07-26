"""Conversation-safe, resumable triggered capture selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from adaptive_synth_eval.capture.models import CaptureTrigger
from adaptive_synth_eval.monitoring.triggers import (
    TriggerPolicy,
    evaluate_row_triggers,
)

SELECTOR_ALGORITHM_VERSION = "conversation-stream-v2"
_SEVERITY = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _row_digest(row: dict[str, Any]) -> str:
    canonical = json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


@dataclass(frozen=True)
class RowLocator:
    line_index: int
    conversation_id: str
    turn_id: str
    row_digest: str

    @classmethod
    def for_row(cls, line_index: int, row: dict[str, Any]) -> "RowLocator":
        return cls(
            line_index=int(line_index),
            conversation_id=str(row.get("conversation_id") or ""),
            turn_id=str(row.get("turn_id") or ""),
            row_digest=_row_digest(row),
        )

    @property
    def key(self) -> str:
        return f"{self.line_index}:{self.row_digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_index": self.line_index,
            "conversation_id": self.conversation_id,
            "turn_id": self.turn_id,
            "row_digest": self.row_digest,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RowLocator":
        return cls(
            line_index=int(raw.get("line_index") or 0),
            conversation_id=str(raw.get("conversation_id") or ""),
            turn_id=str(raw.get("turn_id") or ""),
            row_digest=str(raw.get("row_digest") or ""),
        )


@dataclass(frozen=True)
class TriggerAssociation:
    trigger_id: str
    rule_id: str | None
    source: str
    severity: str
    event_type: str
    detector_name: str
    reason: str
    role: str
    trigger_line_index: int
    distance: int
    policy_fingerprint: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "rule_id": self.rule_id,
            "source": self.source,
            "severity": self.severity,
            "event_type": self.event_type,
            "detector_name": self.detector_name,
            "reason": self.reason,
            "role": self.role,
            "trigger_line_index": self.trigger_line_index,
            "distance": self.distance,
            "policy_fingerprint": self.policy_fingerprint,
        }

    @classmethod
    def from_trigger(
        cls,
        trigger: CaptureTrigger,
        *,
        role: str,
        trigger_line_index: int,
        distance: int,
    ) -> "TriggerAssociation":
        return cls(
            trigger_id=trigger.trigger_id,
            rule_id=trigger.rule_id,
            source=trigger.source.value,
            severity=trigger.severity.value,
            event_type=trigger.event_type,
            detector_name=trigger.detector_name,
            reason=trigger.reason,
            role=role,
            trigger_line_index=trigger_line_index,
            distance=distance,
            policy_fingerprint=trigger.policy_fingerprint,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TriggerAssociation":
        return cls(
            trigger_id=str(raw.get("trigger_id") or ""),
            rule_id=(
                str(raw["rule_id"]) if raw.get("rule_id") is not None else None
            ),
            source=str(raw.get("source") or ""),
            severity=str(raw.get("severity") or "low"),
            event_type=str(raw.get("event_type") or ""),
            detector_name=str(raw.get("detector_name") or ""),
            reason=str(raw.get("reason") or ""),
            role=str(raw.get("role") or "trigger"),
            trigger_line_index=int(raw.get("trigger_line_index") or 0),
            distance=int(raw.get("distance") or 0),
            policy_fingerprint=(
                str(raw["policy_fingerprint"])
                if raw.get("policy_fingerprint") is not None
                else None
            ),
        )


@dataclass
class SelectionCandidate:
    locator: RowLocator
    row: dict[str, Any]
    associations: list[TriggerAssociation] = field(default_factory=list)

    def add(self, association: TriggerAssociation) -> None:
        identity = (
            association.trigger_id,
            association.role,
            association.trigger_line_index,
        )
        if not any(
            (
                current.trigger_id,
                current.role,
                current.trigger_line_index,
            )
            == identity
            for current in self.associations
        ):
            self.associations.append(association)

    def to_snapshot(self) -> dict[str, Any]:
        return {"locator": self.locator.to_dict()}


@dataclass(frozen=True)
class PendingLookahead:
    conversation_id: str
    trigger: dict[str, Any]
    trigger_line_index: int
    remaining: int
    next_distance: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "trigger": self.trigger,
            "trigger_line_index": self.trigger_line_index,
            "remaining": self.remaining,
            "next_distance": self.next_distance,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PendingLookahead":
        return cls(
            conversation_id=str(raw.get("conversation_id") or ""),
            trigger=dict(raw.get("trigger") or {}),
            trigger_line_index=int(raw.get("trigger_line_index") or 0),
            remaining=int(raw.get("remaining") or 0),
            next_distance=int(raw.get("next_distance") or 1),
        )


@dataclass(frozen=True)
class BudgetDrop:
    locator: RowLocator
    associations: tuple[TriggerAssociation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator": self.locator.to_dict(),
            "associations": [
                association.to_dict() for association in self.associations
            ],
        }


@dataclass
class TriggeredSelectionState:
    recent_by_conversation: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    pending: list[PendingLookahead] = field(default_factory=list)
    detected_trigger_ids: list[str] = field(default_factory=list)
    selected_keys: list[str] = field(default_factory=list)
    budget_drops: list[dict[str, Any]] = field(default_factory=list)
    deduplicated_context: int = 0
    selector_algorithm_version: str = SELECTOR_ALGORITHM_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "recent_by_conversation": self.recent_by_conversation,
            "pending": [item.to_dict() for item in self.pending],
            "detected_trigger_ids": self.detected_trigger_ids,
            "selected_keys": self.selected_keys,
            "budget_drops": self.budget_drops,
            "deduplicated_context": self.deduplicated_context,
            "selector_algorithm_version": self.selector_algorithm_version,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "TriggeredSelectionState":
        raw = raw or {}
        recent = raw.get("recent_by_conversation")
        return cls(
            recent_by_conversation=(
                {
                    str(conversation): [
                        {"locator": dict(snapshot["locator"])}
                        for snapshot in snapshots
                        if isinstance(snapshot, dict)
                        and isinstance(snapshot.get("locator"), dict)
                    ]
                    for conversation, snapshots in recent.items()
                    if isinstance(snapshots, list)
                }
                if isinstance(recent, dict)
                else {}
            ),
            pending=[
                PendingLookahead.from_dict(item)
                for item in (raw.get("pending") or [])
                if isinstance(item, dict)
            ],
            detected_trigger_ids=[
                str(value) for value in (raw.get("detected_trigger_ids") or [])
            ],
            selected_keys=[str(value) for value in (raw.get("selected_keys") or [])],
            budget_drops=[
                dict(value)
                for value in (raw.get("budget_drops") or [])
                if isinstance(value, dict)
            ],
            deduplicated_context=int(raw.get("deduplicated_context") or 0),
            selector_algorithm_version=str(
                raw.get("selector_algorithm_version")
                or SELECTOR_ALGORITHM_VERSION
            ),
        )


@dataclass(frozen=True)
class TriggeredSelectionResult:
    rows: list[tuple[int, dict[str, Any]]]
    provenance: dict[int, list[dict[str, Any]]]
    triggers: list[CaptureTrigger]
    state: TriggeredSelectionState
    metrics: dict[str, int]


def _trigger_from_pending(raw: dict[str, Any]) -> CaptureTrigger:
    from adaptive_synth_eval.capture.models import TriggerSeverity, TriggerSource

    return CaptureTrigger(
        trigger_id=str(raw["trigger_id"]),
        source=TriggerSource(str(raw["source"])),
        event_type=str(raw["event_type"]),
        severity=TriggerSeverity(str(raw["severity"])),
        detector_name=str(raw["detector_name"]),
        reason=str(raw["reason"]),
        timestamp=str(raw.get("timestamp") or ""),
        metadata=dict(raw.get("metadata") or {}),
        rule_id=str(raw["rule_id"]) if raw.get("rule_id") is not None else None,
        policy_fingerprint=(
            str(raw["policy_fingerprint"])
            if raw.get("policy_fingerprint") is not None
            else None
        ),
    )


def _candidate_rank(candidate: SelectionCandidate) -> tuple[int, int, int, int]:
    is_trigger = any(item.role == "trigger" for item in candidate.associations)
    rankable = (
        [item for item in candidate.associations if item.role == "trigger"]
        if is_trigger
        else candidate.associations
    )
    best = min(
        rankable,
        key=lambda association: (
            -_SEVERITY.get(association.severity, 0),
            association.distance,
            0 if association.role == "before" else 1,
            association.trigger_line_index,
        ),
    )
    return (
        0 if is_trigger else 1,
        -_SEVERITY.get(best.severity, 0),
        0 if is_trigger else best.distance * 2 + (1 if best.role == "after" else 0),
        candidate.locator.line_index,
    )


def select_triggered_window(
    window_rows: list[tuple[int, dict[str, Any]]],
    *,
    state: TriggeredSelectionState,
    policy: TriggerPolicy,
    run_id: str,
    lookback: int,
    lookahead: int,
    budget: int,
    row_resolver: Callable[[RowLocator], dict[str, Any] | None] | None = None,
) -> TriggeredSelectionResult:
    """Select one processing window with per-conversation context and hard budget."""
    if budget <= 0:
        raise ValueError("budget must be positive")
    candidates: dict[str, SelectionCandidate] = {}
    triggers: list[CaptureTrigger] = []
    pending = list(state.pending)
    detected_ids = list(state.detected_trigger_ids)
    detected_set = set(detected_ids)
    deduplicated = state.deduplicated_context
    current_rows: dict[str, dict[str, Any]] = {}

    def candidate_for(line_index: int, row: dict[str, Any]) -> SelectionCandidate:
        nonlocal deduplicated
        locator = RowLocator.for_row(line_index, row)
        existing = candidates.get(locator.key)
        if existing is not None:
            deduplicated += 1
            return existing
        created = SelectionCandidate(locator=locator, row=dict(row))
        candidates[locator.key] = created
        current_rows[locator.key] = created.row
        return created

    def resolve_snapshot(snapshot: dict[str, Any]) -> tuple[RowLocator, dict[str, Any]] | None:
        raw_locator = snapshot.get("locator")
        if not isinstance(raw_locator, dict):
            return None
        locator = RowLocator.from_dict(raw_locator)
        row = snapshot.get("row")
        if not isinstance(row, dict):
            row = current_rows.get(locator.key)
        if not isinstance(row, dict) and row_resolver is not None:
            row = row_resolver(locator)
        if not isinstance(row, dict):
            return None
        if RowLocator.for_row(locator.line_index, row).row_digest != locator.row_digest:
            return None
        return locator, row

    for line_index, row in window_rows:
        conversation_id = str(row.get("conversation_id") or "")
        current = candidate_for(line_index, row)

        next_pending: list[PendingLookahead] = []
        for item in pending:
            if item.remaining <= 0:
                continue
            if item.conversation_id != conversation_id:
                next_pending.append(item)
                continue
            trigger = _trigger_from_pending(item.trigger)
            current.add(
                TriggerAssociation.from_trigger(
                    trigger,
                    role="after",
                    trigger_line_index=item.trigger_line_index,
                    distance=item.next_distance,
                )
            )
            if item.remaining > 1:
                next_pending.append(
                    PendingLookahead(
                        conversation_id=item.conversation_id,
                        trigger=item.trigger,
                        trigger_line_index=item.trigger_line_index,
                        remaining=item.remaining - 1,
                        next_distance=item.next_distance + 1,
                    )
                )
        pending = next_pending

        row_triggers = evaluate_row_triggers(
            row,
            policy,
            run_id,
            conversation_id,
            str(row.get("turn_id") or ""),
        )
        triggers.extend(row_triggers)
        recent = state.recent_by_conversation.get(conversation_id, [])
        for trigger in row_triggers:
            if trigger.trigger_id not in detected_set:
                detected_ids.append(trigger.trigger_id)
                detected_set.add(trigger.trigger_id)
            current.add(
                TriggerAssociation.from_trigger(
                    trigger,
                    role="trigger",
                    trigger_line_index=line_index,
                    distance=0,
                )
            )
            for distance, snapshot in enumerate(reversed(recent[-lookback:]), 1):
                resolved = resolve_snapshot(snapshot)
                if resolved is None:
                    continue
                locator, prior_row = resolved
                before = candidate_for(locator.line_index, prior_row)
                before.add(
                    TriggerAssociation.from_trigger(
                        trigger,
                        role="before",
                        trigger_line_index=line_index,
                        distance=distance,
                    )
                )
            if lookahead:
                pending.append(
                    PendingLookahead(
                        conversation_id=conversation_id,
                        trigger=trigger.to_dict(),
                        trigger_line_index=line_index,
                        remaining=lookahead,
                        next_distance=1,
                    )
                )

        snapshots = state.recent_by_conversation.setdefault(conversation_id, [])
        snapshots.append(current.to_snapshot())
        if lookback:
            state.recent_by_conversation[conversation_id] = snapshots[-lookback:]
        else:
            state.recent_by_conversation[conversation_id] = []

    associated = [
        candidate for candidate in candidates.values() if candidate.associations
    ]
    ranked = sorted(associated, key=_candidate_rank)
    selected = ranked[:budget]
    dropped = ranked[budget:]
    selected_keys = list(state.selected_keys)
    selected_set = set(selected_keys)
    for candidate in selected:
        if candidate.locator.key not in selected_set:
            selected_keys.append(candidate.locator.key)
            selected_set.add(candidate.locator.key)
    drops = list(state.budget_drops)
    drops.extend(
        BudgetDrop(
            locator=candidate.locator,
            associations=tuple(candidate.associations),
        ).to_dict()
        for candidate in dropped
    )
    new_state = TriggeredSelectionState(
        recent_by_conversation=state.recent_by_conversation,
        pending=pending,
        detected_trigger_ids=detected_ids,
        selected_keys=selected_keys,
        budget_drops=drops,
        deduplicated_context=deduplicated,
    )
    selected_in_source_order = sorted(
        ((candidate.locator.line_index, candidate.row) for candidate in selected),
        key=lambda item: item[0],
    )
    provenance = {
        candidate.locator.line_index: [
            association.to_dict() for association in candidate.associations
        ]
        for candidate in selected
    }
    return TriggeredSelectionResult(
        rows=selected_in_source_order,
        provenance=provenance,
        triggers=triggers,
        state=new_state,
        metrics={
            "triggers_detected": len({trigger.trigger_id for trigger in triggers}),
            "rows_promoted": len(selected),
            "budget_used": len(selected),
            "budget_drops": len(dropped),
            "deduplicated_context": deduplicated - state.deduplicated_context,
            "pending_lookahead": len(pending),
        },
    )
