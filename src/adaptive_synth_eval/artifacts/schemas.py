from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class ChatHistoryRecord:
    conversation_id: str
    session_id: str
    synthetic_day: date
    persona_id: str
    scenario_id: str
    turn_id: int
    user_message: str
    bot_response: str
    expected_retrieval_topics: list[str]
    planned_failure_modes: list[str]
    applied_failure_modes: list[str]
    groundedness_score: float | None = None
    relevance_score: float | None = None
    safety_score: float | None = None
    clarification_score: float | None = None
    failure_mode: str | None = None
    latency_ms: float | None = None
    error: str | None = None
    synthetic_flag: bool = True
    retrieved_policy_ids: list[str] | None = None
    response_raw: dict[str, Any] | None = None
    generation_metadata: dict[str, Any] | None = None
    reference_context: str | None = None
    reference_answer: str | None = None
    capture_events: list[dict[str, Any]] | None = None
    status_code: int | None = None
    timestamp: str | None = None
    sequence: int | None = None
    recipe_id: str | None = None
    synthetic_timestamp: str | None = None
    synthetic_slot: int | None = None
    profile_period_id: str | None = None
    profile_period_instance_id: str | None = None
    profile_period_start: str | None = None
    profile_period_end: str | None = None
    conversation_mode: str | None = None
    behavior_mode: str | None = None
    traffic_weight: float | None = None
    recipe_weights: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["synthetic_day"] = self.synthetic_day.isoformat()
        for field_name in (
            "timestamp",
            "sequence",
            "recipe_id",
            "synthetic_timestamp",
            "synthetic_slot",
            "profile_period_id",
            "profile_period_instance_id",
            "profile_period_start",
            "profile_period_end",
            "conversation_mode",
            "behavior_mode",
            "traffic_weight",
            "recipe_weights",
        ):
            if data[field_name] is None:
                data.pop(field_name)
        return data
