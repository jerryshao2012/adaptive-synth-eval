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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["synthetic_day"] = self.synthetic_day.isoformat()
        return data
