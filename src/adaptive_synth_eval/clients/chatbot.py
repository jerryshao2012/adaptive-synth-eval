from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from adaptive_synth_eval.clients.logger_utils import setup_logger
from adaptive_synth_eval.clients.retry_utils import retry_on_rate_limit
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = setup_logger(__name__)

# Configuration from environment variables
RAG_ENDPOINT = os.getenv("RAG_ENDPOINT")
RAG_TIMEOUT = os.getenv("RAG_TIMEOUT", "60.0")
RAG_MODEL = os.getenv("RAG_MODEL")
RAG_TEMPERATURE = os.getenv("RAG_TEMPERATURE")
RAG_SOURCE_DOCUMENT_REFERENCE = os.getenv("RAG_SOURCE_DOCUMENT_REFERENCE")
CHATBOT_API_TOKEN = os.getenv("CHATBOT_API_TOKEN")


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
        logger.info("Initializing ChatbotClient")
        self.endpoint = endpoint or RAG_ENDPOINT
        logger.debug(f"Chatbot endpoint: {self.endpoint or 'Not set'}")

        self.enabled = enabled
        logger.debug(f"Chatbot enabled: {self.enabled}")

        self.auth = auth or {}
        if not self.auth and CHATBOT_API_TOKEN:
            self.auth = {"type": "bearer", "env_var": "CHATBOT_API_TOKEN"}
            logger.debug("Using CHATBOT_API_TOKEN for authentication")

        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds
        else:
            self.timeout_seconds = float(RAG_TIMEOUT)
        logger.debug(f"Request timeout: {self.timeout_seconds}s")

        # Optional RAG specific configs
        self.rag_model = RAG_MODEL
        if self.rag_model:
            self.rag_model = [m.strip() for m in self.rag_model.split(",")]
            logger.debug(f"RAG models configured: {self.rag_model}")

        self.rag_temperature = float(RAG_TEMPERATURE) if RAG_TEMPERATURE else None
        if self.rag_temperature is not None:
            logger.debug(f"RAG temperature: {self.rag_temperature}")

        self.source_doc_ref = RAG_SOURCE_DOCUMENT_REFERENCE
        if self.source_doc_ref:
            logger.debug(f"Source document reference: {self.source_doc_ref}")

        logger.info("ChatbotClient initialized successfully")

    def send(
            self,
            *,
            conversation_id: str,
            session_id: str,
            turn_id: int,
            user_message: str,
            metadata: dict[str, Any] | None = None,
    ) -> ChatbotResponse:
        logger.info(
            f"Sending message - conversation_id: {conversation_id}, session_id: {session_id}, turn_id: {turn_id}")
        logger.debug(f"User message length: {len(user_message)} chars")

        if not self.enabled or not self.endpoint:
            logger.warning("Chatbot is disabled or endpoint not configured, returning mock response")
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
            logger.debug("Attempting to send request with retry logic")
            result = self._send_with_retry(
                conversation_id=conversation_id,
                session_id=session_id,
                turn_id=turn_id,
                user_message=user_message,
                metadata=metadata,
            )
            logger.info(f"Request completed - status: {result.status_code}, latency: {result.latency_ms}ms")
            if result.error:
                logger.error(f"Request returned error: {result.error}")
            return result
        except Exception as exc:
            logger.exception(f"Exception occurred while sending message: {exc}")
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
        logger.debug(f"Preparing request to endpoint: {self.endpoint}")

        headers = {"Content-Type": "application/json"}
        if self.auth.get("type") == "bearer" and self.auth.get("env_var"):
            token = os.getenv(str(self.auth["env_var"]))
            if token:
                headers["Authorization"] = f"Bearer {token}"
                logger.debug("Authorization header added")
            else:
                logger.warning(f"Auth token not found in environment variable: {self.auth['env_var']}")

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
            logger.debug(f"RAG config added: {butler_config}")

            # Default bmo_content if using RAG mode
            payload["bmo_content"] = ["Policies and Procedures"]
            logger.debug("Default bmo_content set to Policies and Procedures")

        if metadata:
            payload["metadata"] = metadata
            logger.debug(f"Metadata included in payload: {list(metadata.keys())}")

        logger.debug(f"Sending POST request with payload keys: {list(payload.keys())}")
        start = time.perf_counter()
        response = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout_seconds)
        latency_ms = (time.perf_counter() - start) * 1000
        status_code = response.status_code

        logger.debug(f"Response received - status: {status_code}, latency: {latency_ms:.2f}ms")

        try:
            body = response.json()
            logger.debug(
                f"Response body parsed successfully, keys: {list(body.keys()) if isinstance(body, dict) else 'N/A'}")
        except ValueError:
            body = {"text": response.text}
            logger.warning(f"Failed to parse JSON response, using text fallback. Response length: {len(response.text)}")

        error = None if response.ok else f"HTTP {status_code}"
        if error:
            logger.error(f"Request failed with error: {error}")
            logger.debug(f"Response content: {response.text[:500]}")

        return ChatbotResponse.from_payload(body, latency_ms=round(latency_ms, 2), status_code=status_code,
                                            error=error)


def extract_bot_text(payload: dict[str, Any]) -> str:
    for key in ("response", "answer", "message", "content", "text", "llm_response"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return ""
