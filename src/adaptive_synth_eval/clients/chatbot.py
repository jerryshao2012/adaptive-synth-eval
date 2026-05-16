from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class ChatbotResponse:
    raw: dict[str, Any]
    bot_response: str
    latency_ms: float | None
    status_code: int
    error: str | None = None
    retrieved_policy_ids: list[str] | None = None

    @classmethod
    def from_payload(
            cls,
            payload: dict[str, Any],
            *,
            latency_ms: float | None,
            status_code: int,
            error: str | None = None,
    ) -> "ChatbotResponse":
        text = extract_bot_text(payload)
        retrieved = payload.get("retrieved_policy_ids")
        return cls(
            raw=payload,
            bot_response=text,
            latency_ms=latency_ms,
            status_code=status_code,
            error=error,
            retrieved_policy_ids=list(retrieved) if isinstance(retrieved, list) else None,
        )


class ChatbotClient:
    def __init__(
            self,
            *,
            endpoint: str | None = None,
            enabled: bool = True,
            auth: dict[str, Any] | None = None,
            timeout_seconds: float = 60.0,
    ):
        self.endpoint = endpoint
        self.enabled = enabled
        self.auth = auth or {}
        self.timeout_seconds = timeout_seconds

    def send(
            self,
            *,
            conversation_id: str,
            session_id: str,
            turn_id: int,
            user_message: str,
            metadata: dict[str, Any] | None = None,
    ) -> ChatbotResponse:
        if not self.enabled or not self.endpoint:
            return ChatbotResponse.from_payload(
                {
                    "mock": True,
                    "response": f"[dry-run chatbot response for turn {turn_id}]",
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                },
                latency_ms=0.0,
                status_code=0,
            )

        headers = {"Content-Type": "application/json"}
        if self.auth.get("type") == "bearer" and self.auth.get("env_var"):
            token = os.getenv(str(self.auth["env_var"]))
            if token:
                headers["Authorization"] = f"Bearer {token}"

        payload = {
            "conversation_id": conversation_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "user_message": user_message,
        }
        if metadata:
            payload["metadata"] = metadata

        try:
            start = time.perf_counter()
            response = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout_seconds)
            latency_ms = (time.perf_counter() - start) * 1000
            status_code = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = {"text": response.text}
            error = None if response.ok else f"HTTP {status_code}"
            return ChatbotResponse.from_payload(body, latency_ms=round(latency_ms, 2), status_code=status_code,
                                                error=error)
        except Exception as exc:
            return ChatbotResponse.from_payload({}, latency_ms=None, status_code=0, error=str(exc))


def extract_bot_text(payload: dict[str, Any]) -> str:
    for key in ("response", "answer", "message", "content", "text", "llm_response"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return ""
