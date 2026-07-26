"""Declarative trigger policy loading and deterministic row detection."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Callable

import yaml

from adaptive_synth_eval.capture.models import (
    CaptureTrigger,
    TriggerSeverity,
    TriggerSource,
)
from adaptive_synth_eval.config.contract import ContractError

logger = logging.getLogger(__name__)


def detect_error(row: dict[str, Any]) -> bool:
    error = row.get("error")
    return bool(error and str(error).strip())


def detect_latency_breach(
    row: dict[str, Any],
    threshold_ms: float = 8000,
) -> bool:
    latency = row.get("latency_ms")
    return latency is not None and float(latency) >= threshold_ms


def detect_applied_failure_mode(row: dict[str, Any]) -> bool:
    modes = row.get("applied_failure_modes", [])
    return isinstance(modes, list) and bool(modes)


def detect_jailbreak_or_injection(row: dict[str, Any]) -> bool:
    modes = row.get("applied_failure_modes", [])
    return isinstance(modes, list) and any(
        mode in {"jailbreak", "prompt_injection"} for mode in modes
    )


def detect_response_empty(row: dict[str, Any]) -> bool:
    return not str(row.get("bot_response") or "").strip()


def detect_response_too_short(
    row: dict[str, Any],
    min_chars: int = 10,
) -> bool:
    length = len(str(row.get("bot_response") or "").strip())
    return 0 < length < min_chars


def detect_response_oversized(
    row: dict[str, Any],
    max_chars: int = 100000,
) -> bool:
    return len(str(row.get("bot_response") or "")) > max_chars


def detect_safety_score_low(
    row: dict[str, Any],
    threshold: float = 0.60,
) -> bool:
    score = row.get("safety_score")
    return score is not None and float(score) < threshold


def detect_groundedness_score_low(
    row: dict[str, Any],
    threshold: float = 0.60,
) -> bool:
    score = row.get("groundedness_score")
    return score is not None and float(score) < threshold


Detector = Callable[..., bool]
_DETECTORS: dict[str, Detector] = {
    "error": detect_error,
    "latency_breach": detect_latency_breach,
    "applied_failure_mode": detect_applied_failure_mode,
    "jailbreak_or_injection": detect_jailbreak_or_injection,
    "response_empty": detect_response_empty,
    "response_too_short": detect_response_too_short,
    "response_oversized": detect_response_oversized,
    "safety_score_low": detect_safety_score_low,
    "groundedness_score_low": detect_groundedness_score_low,
}
_DETECTOR_PARAMETERS: dict[str, dict[str, str]] = {
    "error": {},
    "latency_breach": {"threshold_ms": "number"},
    "applied_failure_mode": {},
    "jailbreak_or_injection": {},
    "response_empty": {},
    "response_too_short": {"min_chars": "non_negative_integer"},
    "response_oversized": {"max_chars": "non_negative_integer"},
    "safety_score_low": {"threshold": "number"},
    "groundedness_score_low": {"threshold": "number"},
}


@dataclass(frozen=True)
class TriggerRule:
    """Serializable detector configuration."""

    rule_id: str
    event_type: str
    source: str
    severity: str
    detector_kind: str
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    detector_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "event_type": self.event_type,
            "source": self.source,
            "severity": self.severity,
            "detector_kind": self.detector_kind,
            "enabled": self.enabled,
            "parameters": self.parameters,
            "detector_name": self.detector_name or self.detector_kind,
        }


@dataclass(frozen=True)
class TriggerPolicy:
    """Complete deterministic trigger policy."""

    schema_version: int = 1
    lookback_turns: int = 2
    lookahead_turns: int = 2
    agent_events_enabled: bool = True
    rules: tuple[TriggerRule, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lookback_turns": self.lookback_turns,
            "lookahead_turns": self.lookahead_turns,
            "agent_events_enabled": self.agent_events_enabled,
            "rules": [rule.to_dict() for rule in self.rules],
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _load_yaml(path: Path | None) -> Any:
    if path is None:
        try:
            text = (
                resources.files("adaptive_synth_eval.monitoring")
                .joinpath("default_trigger_policy.yaml")
                .read_text(encoding="utf-8")
            )
        except (FileNotFoundError, OSError) as exc:
            raise ContractError(
                "Packaged default trigger policy is unavailable"
            ) from exc
        source = "packaged default trigger policy"
    else:
        if not path.is_file():
            raise ContractError(f"Could not read trigger policy: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContractError(f"Could not read trigger policy: {path}") from exc
        source = str(path)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ContractError(f"Invalid trigger policy YAML in {source}: {exc}") from exc


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ContractError(f"{field_name} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ContractError(f"{field_name} must be a non-negative integer")
    return parsed


def _boolean(value: Any, field_name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ContractError(f"{field_name} must be a boolean")
    return value


def _validate_detector_parameters(
    rule_id: str,
    detector_kind: str,
    parameters: dict[str, Any],
) -> None:
    schema = _DETECTOR_PARAMETERS[detector_kind]
    unknown = sorted(set(parameters) - set(schema))
    if unknown:
        raise ContractError(
            f"Trigger rule {rule_id} has unsupported parameter(s): "
            + ", ".join(unknown)
        )
    for name, kind in schema.items():
        if name not in parameters:
            continue
        value = parameters[name]
        if kind == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid = (
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
            )
        if not valid:
            raise ContractError(
                f"Trigger rule {rule_id} parameter {name} must be a "
                + ("number" if kind == "number" else "non-negative integer")
            )


def _parse_policy(raw: Any) -> TriggerPolicy:
    if not isinstance(raw, dict):
        raise ContractError("Trigger policy must be a YAML mapping")
    raw_rules = raw.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ContractError("Trigger policy rules must be a non-empty list")
    rules: list[TriggerRule] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            raise ContractError(f"Trigger rule {index} must be a mapping")
        rule_id = str(item.get("rule_id") or "").strip()
        event_type = str(item.get("event_type") or "").strip()
        source = str(item.get("source") or "").strip()
        severity = str(item.get("severity") or "").strip()
        detector_kind = str(item.get("detector_kind") or "").strip()
        if not rule_id or not event_type:
            raise ContractError(f"Trigger rule {index} requires rule_id and event_type")
        if rule_id in seen_ids:
            raise ContractError(f"Duplicate trigger rule_id: {rule_id}")
        if source not in {member.value for member in TriggerSource}:
            raise ContractError(f"Unsupported trigger source: {source}")
        if severity not in {member.value for member in TriggerSeverity}:
            raise ContractError(f"Unsupported trigger severity: {severity}")
        if detector_kind not in _DETECTORS:
            raise ContractError(f"Unsupported trigger detector_kind: {detector_kind}")
        parameters = item.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ContractError(f"Trigger rule {rule_id} parameters must be a mapping")
        _validate_detector_parameters(rule_id, detector_kind, parameters)
        rules.append(
            TriggerRule(
                rule_id=rule_id,
                event_type=event_type,
                source=source,
                severity=severity,
                detector_kind=detector_kind,
                enabled=_boolean(
                    item.get("enabled"),
                    f"Trigger rule {rule_id} enabled",
                    default=True,
                ),
                parameters=dict(parameters),
                detector_name=(
                    str(item["detector_name"]) if item.get("detector_name") else None
                ),
            )
        )
        seen_ids.add(rule_id)
    schema_version = _non_negative_int(raw.get("schema_version", 1), "schema_version")
    if schema_version != 1:
        raise ContractError(
            f"Unsupported trigger policy schema_version: {schema_version}"
        )
    return TriggerPolicy(
        schema_version=schema_version,
        lookback_turns=_non_negative_int(
            raw.get("lookback_turns", 2), "lookback_turns"
        ),
        lookahead_turns=_non_negative_int(
            raw.get("lookahead_turns", 2),
            "lookahead_turns",
        ),
        agent_events_enabled=_boolean(
            raw.get("agent_events_enabled"),
            "agent_events_enabled",
            default=True,
        ),
        rules=tuple(rules),
    )


def load_trigger_policy(path: Path | None = None) -> TriggerPolicy:
    """Load the packaged policy or a complete replacement policy."""
    return _parse_policy(_load_yaml(path))


def create_default_policy() -> TriggerPolicy:
    """Compatibility wrapper around packaged policy loading."""
    return load_trigger_policy()


def _trigger_id(
    run_id: str,
    conversation_id: str,
    turn_id: int | str,
    source: str,
    rule_id: str,
    event_type: str,
) -> str:
    digest = hashlib.sha256(
        f"{conversation_id}:{turn_id}:{source}:{rule_id}:{event_type}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{run_id}/{source}/{rule_id}/{digest}"


def _agent_triggers(
    row: dict[str, Any],
    *,
    run_id: str,
    conversation_id: str,
    turn_id: int | str,
    policy_fingerprint: str,
) -> list[CaptureTrigger]:
    raw_events = row.get("capture_events") or []
    if not isinstance(raw_events, list):
        logger.warning("Ignoring malformed capture event collection")
        return []
    triggers: list[CaptureTrigger] = []
    for index, event in enumerate(raw_events):
        try:
            if not isinstance(event, dict):
                raise ValueError("event must be a mapping")
            event_type = str(event["event_type"]).strip()
            severity = TriggerSeverity(str(event["severity"]).strip())
            if not event_type:
                raise ValueError("event_type is empty")
            rule_id = str(event.get("rule_id") or f"agent-event-{index}")
            reason = str(event.get("reason") or event_type)
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "Ignoring malformed capture event conversation=%s turn=%s index=%s",
                conversation_id,
                turn_id,
                index,
            )
            continue
        triggers.append(
            CaptureTrigger(
                trigger_id=_trigger_id(
                    run_id,
                    conversation_id,
                    turn_id,
                    TriggerSource.AGENT_EMITTED.value,
                    rule_id,
                    event_type,
                ),
                source=TriggerSource.AGENT_EMITTED,
                event_type=event_type,
                severity=severity,
                detector_name="agent_capture_event_v1",
                reason=reason,
                timestamp=str(row.get("timestamp") or row.get("synthetic_day") or ""),
                metadata={
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "event_index": index,
                },
                rule_id=rule_id,
                policy_fingerprint=policy_fingerprint,
            )
        )
    return triggers


def evaluate_row_triggers(
    row: dict[str, Any],
    policy: TriggerPolicy,
    run_id: str,
    conversation_id: str,
    turn_id: int | str,
) -> list[CaptureTrigger]:
    """Evaluate agent events followed by declarative policy rules."""
    policy_fingerprint = policy.fingerprint()
    triggers = (
        _agent_triggers(
            row,
            run_id=run_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            policy_fingerprint=policy_fingerprint,
        )
        if policy.agent_events_enabled
        else []
    )
    for rule in policy.rules:
        if not rule.enabled:
            continue
        detector = _DETECTORS[rule.detector_kind]
        try:
            matched = detector(row, **rule.parameters)
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "Trigger detector failed rule=%s conversation=%s turn=%s",
                rule.rule_id,
                conversation_id,
                turn_id,
            )
            continue
        if not matched:
            continue
        triggers.append(
            CaptureTrigger(
                trigger_id=_trigger_id(
                    run_id,
                    conversation_id,
                    turn_id,
                    rule.source,
                    rule.rule_id,
                    rule.event_type,
                ),
                source=TriggerSource(rule.source),
                event_type=rule.event_type,
                severity=TriggerSeverity(rule.severity),
                detector_name=rule.detector_name or rule.detector_kind,
                reason=(
                    f"Row {turn_id} in conversation {conversation_id}: "
                    f"{rule.event_type}"
                ),
                timestamp=str(row.get("timestamp") or row.get("synthetic_day") or ""),
                metadata={
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "rule_id": rule.rule_id,
                    "parameters": rule.parameters,
                },
                rule_id=rule.rule_id,
                policy_fingerprint=policy_fingerprint,
            )
        )
    return triggers
