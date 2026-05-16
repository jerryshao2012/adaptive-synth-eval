from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from adaptive_synth_eval.clients.retry_utils import retry_on_rate_limit


@dataclass(frozen=True)
class ChatbotResponse:
    raw: dict[str, Any]
    bot_response: str
    latency_ms: float | None
    status_code: int
    error: str | None = None
    retrieved_policy_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None

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
            metadata={
                "retrieved_content": payload.get("retrieved_content", {}),
                "used_bmo_content": payload.get("used_bmo_content", []),
                "graph": payload.get("graph", ""),
                "references": payload.get("references", ""),
            }
        )


class ChatbotClient:
    def __init__(
            self,
            *,
            endpoint: str | None = None,
            enabled: bool = True,
            auth: dict[str, Any] | None = None,
            timeout_seconds: float | None = None,
    ):
        self.endpoint = endpoint or os.getenv("RAG_ENDPOINT")
        self.enabled = enabled
        self.auth = auth or {}
        if not self.auth and os.getenv("CHATBOT_API_TOKEN"):
            self.auth = {"type": "bearer", "env_var": "CHATBOT_API_TOKEN"}

        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds
        else:
            self.timeout_seconds = float(os.getenv("RAG_TIMEOUT", "60.0"))

        # Optional RAG specific configs
        self.rag_model = os.getenv("RAG_MODEL")
        if self.rag_model:
            self.rag_model = [m.strip() for m in self.rag_model.split(",")]

        temp_str = os.getenv("RAG_TEMPERATURE")
        self.rag_temperature = float(temp_str) if temp_str else None
        self.source_doc_ref = os.getenv("RAG_SOURCE_DOCUMENT_REFERENCE")

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

        try:
            return self._send_with_retry(
                conversation_id=conversation_id,
                session_id=session_id,
                turn_id=turn_id,
                user_message=user_message,
                metadata=metadata,
            )
        except Exception as exc:
            return ChatbotResponse.from_payload({}, latency_ms=None, status_code=0, error=str(exc))

    @retry_on_rate_limit(max_retries=3, initial_backoff=1.0, max_backoff=30.0)
    def _send_with_retry(
            self,
            *,
            conversation_id: str,
            session_id: str,
            turn_id: int,
            user_message: str,
            metadata: dict[str, Any] | None = None,
    ) -> ChatbotResponse:
        headers = {"Content-Type": "application/json"}
        if self.auth.get("type") == "bearer" and self.auth.get("env_var"):
            token = os.getenv(str(self.auth["env_var"]))
            if token:
                headers["Authorization"] = f"Bearer {token}"

        # Unified payload: support legacy params and config-driven parameters
        payload = {
            "conversation_id": conversation_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "user_message": user_message,
            "query": user_message,
        }

        # Add RAG config if defined
        if self.rag_model or self.rag_temperature is not None or self.source_doc_ref:
            butler_config = {}
            if self.rag_model:
                butler_config["rag_model"] = self.rag_model
            if self.rag_temperature is not None:
                butler_config["rag_temperature"] = self.rag_temperature
            if self.source_doc_ref is not None:
                butler_config["source_document_reference"] = self.source_doc_ref
            payload["butler_11m_config"] = butler_config

            # Default bmo_content if using RAG mode
            payload["bmo_content"] = ["Policies and Procedures"]

        if metadata:
            payload["metadata"] = metadata

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


def extract_bot_text(payload: dict[str, Any]) -> str:
    for key in ("response", "answer", "message", "content", "text", "llm_response"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return ""
