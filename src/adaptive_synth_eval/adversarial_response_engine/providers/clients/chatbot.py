"""Production-grade chatbot client with retry, rate-limiting, and latency tracking."""
# Sibling copy exists at adaptive_synth_eval/clients/chatbot.py — keep in sync manually.

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

from .logger_utils import setup_logger
from .retry_utils import retry_on_rate_limit

load_dotenv()

logger = setup_logger(__name__)

DEFAULT_TIMEOUT = "60.0"


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
            },
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
        self.endpoint = endpoint or os.getenv("CHATBOT_ENDPOINT")
        self.enabled = enabled
        self.auth = auth or {}
        if not self.auth and os.getenv("CHATBOT_API_TOKEN"):
            self.auth = {"type": "bearer", "env_var": "CHATBOT_API_TOKEN"}
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.getenv("CHATBOT_TIMEOUT", DEFAULT_TIMEOUT))
        )
        self.chatbot_model = os.getenv("CHATBOT_MODEL")
        if self.chatbot_model:
            self.chatbot_model = [m.strip() for m in self.chatbot_model.split(",")]
        self.chatbot_temperature = os.getenv("CHATBOT_TEMPERATURE")
        if self.chatbot_temperature is not None:
            self.chatbot_temperature = float(self.chatbot_temperature)
        self.source_doc_ref = os.getenv("CHATBOT_SOURCE_DOCUMENT_REFERENCE")

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
                {"mock": True, "response": f"[dry-run chatbot response for turn {turn_id}]"},
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
            logger.exception(f"ChatbotClient.send failed: {exc}")
            return ChatbotResponse.from_payload({}, latency_ms=None, status_code=0, error=str(exc))

    async def send_async(
            self,
            *,
            conversation_id: str,
            session_id: str,
            turn_id: int,
            user_message: str,
            metadata: dict[str, Any] | None = None,
    ) -> ChatbotResponse:
        return await asyncio.to_thread(
            self.send,
            conversation_id=conversation_id,
            session_id=session_id,
            turn_id=turn_id,
            user_message=user_message,
            metadata=metadata,
        )

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

        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "user_message": user_message,
            "query": user_message,
        }

        if self.chatbot_model or self.chatbot_temperature is not None or self.source_doc_ref:
            butler_config: dict[str, Any] = {}
            if self.chatbot_model:
                butler_config["chatbot_model"] = self.chatbot_model
            if self.chatbot_temperature is not None:
                butler_config["chatbot_temperature"] = self.chatbot_temperature
            if self.source_doc_ref:
                butler_config["source_document_reference"] = self.source_doc_ref
            payload["butler_11m_config"] = butler_config
            payload["bmo_content"] = ["Policies and Procedures"]

        if metadata:
            payload["metadata"] = metadata

        if not self.endpoint:
            raise ValueError("Chatbot endpoint is not configured")

        start = time.perf_counter()
        response = requests.post(
            self.endpoint, json=payload, headers=headers, timeout=self.timeout_seconds
        )
        latency_ms = (time.perf_counter() - start) * 1000

        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text}

        error = None if response.ok else f"HTTP {response.status_code}"
        return ChatbotResponse.from_payload(
            body,
            latency_ms=round(latency_ms, 2),
            status_code=response.status_code,
            error=error,
        )


def extract_bot_text(payload: dict[str, Any]) -> str:
    for key in ("response", "answer", "message", "content", "text", "llm_response"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return ""
