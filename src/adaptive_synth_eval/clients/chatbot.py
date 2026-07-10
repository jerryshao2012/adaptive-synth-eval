from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

from adaptive_synth_eval.clients.logger_utils import setup_logger
from adaptive_synth_eval.clients.retry_utils import is_transient_error, retry_on_exception

# Load environment variables
load_dotenv()

logger = setup_logger(__name__)

# Module-level defaults (still can be overridden)
DEFAULT_TIMEOUT = "60.0"


class RetryableChatbotError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _is_no_response_text(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {
        "",
        "no response generated",
        "no response",
        "empty response",
    }


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
            retry_max_retries: int | None = None,
            retry_initial_backoff: float | None = None,
            retry_max_backoff: float | None = None,
            retry_backoff_multiplier: float | None = None,
            retry_jitter: bool | None = None,
            retry_on_timeout: bool = True,
            retry_on_http_5xx: bool = False,
            chatbot_model: list[str] | None = None,
            chatbot_temperature: float | None = None,
            source_doc_ref: str | None = None,
    ):
        logger.info("Initializing ChatbotClient")
        self.endpoint = endpoint or os.getenv("CHATBOT_ENDPOINT")
        logger.debug(f"Chatbot endpoint: {self.endpoint or 'Not set'}")

        self.enabled = enabled
        logger.debug(f"Chatbot enabled: {self.enabled}")

        self.auth = auth or {}
        if not self.auth and os.getenv("CHATBOT_API_TOKEN"):
            self.auth = {"type": "bearer", "env_var": "CHATBOT_API_TOKEN"}
            logger.debug("Using CHATBOT_API_TOKEN for authentication")

        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds
        else:
            self.timeout_seconds = float(os.getenv("CHATBOT_TIMEOUT", DEFAULT_TIMEOUT))
        logger.debug(f"Request timeout: {self.timeout_seconds}s")

        self.retry_on_timeout = retry_on_timeout
        self.retry_on_http_5xx = retry_on_http_5xx

        # Optional Chatbot specific configs — constructor args take precedence over env vars
        if chatbot_model is not None:
            self.chatbot_model = list(chatbot_model)
        else:
            env_model = os.getenv("CHATBOT_MODEL")
            self.chatbot_model = [m.strip() for m in env_model.split(",")] if env_model else None
        if self.chatbot_model:
            logger.debug(f"Chatbot models configured: {self.chatbot_model}")

        if chatbot_temperature is not None:
            self.chatbot_temperature = float(chatbot_temperature)
        else:
            env_temp = os.getenv("CHATBOT_TEMPERATURE")
            self.chatbot_temperature = float(env_temp) if env_temp is not None else None
        if self.chatbot_temperature is not None:
            logger.debug(f"Chatbot temperature: {self.chatbot_temperature}")

        if source_doc_ref is not None:
            self.source_doc_ref = source_doc_ref
        else:
            self.source_doc_ref = os.getenv("CHATBOT_SOURCE_DOCUMENT_REFERENCE")
        if self.source_doc_ref:
            logger.debug(f"Source document reference: {self.source_doc_ref}")

        self._send_with_retry = retry_on_exception(
            self._send_once,
            max_retries=retry_max_retries,
            initial_backoff=retry_initial_backoff,
            max_backoff=retry_max_backoff,
            backoff_multiplier=retry_backoff_multiplier,
            jitter=retry_jitter,
            should_retry=self._is_chatbot_retryable_error,
            retry_label="Chatbot transient",
        )

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

        if not self.enabled:
            logger.warning("Chatbot is disabled or endpoint not configured, returning mock response")
            mock_response = (
                "This is a comprehensive mock response for testing purposes. "
                "The chatbot is currently disabled in dry-run mode. "
                f"Turn {turn_id}: Based on your question about '{user_message[:50]}...', "
                "I would normally provide a detailed, personalized response tailored to your situation. "
                "This mock response allows you to test the conversation flow without hitting a live endpoint."
            )
            return ChatbotResponse.from_payload(
                {
                    "mock": True,
                    "response": mock_response,
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                },
                latency_ms=0.0,
                status_code=0,
            )

        if not self.endpoint:
            error = "Chatbot endpoint is not configured"
            logger.error(error)
            mock_response = (
                "Mock response: Chatbot endpoint not configured. "
                "Please set CHATBOT_ENDPOINT environment variable or provide endpoint in config."
            )
            return ChatbotResponse.from_payload(
                {},
                latency_ms=None,
                status_code=0,
                error=error
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
            if isinstance(exc, RetryableChatbotError):
                return ChatbotResponse.from_payload(
                    {},
                    latency_ms=None,
                    status_code=exc.status_code or 0,
                    error=str(exc),
                )
            logger.exception(f"Exception occurred while sending message: {exc}")
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
        """Async wrapper around send() for the async simulation pipeline."""
        return await asyncio.to_thread(
            self.send,
            conversation_id=conversation_id,
            session_id=session_id,
            turn_id=turn_id,
            user_message=user_message,
            metadata=metadata,
        )

    def _is_chatbot_retryable_error(self, error: Exception) -> bool:
        if isinstance(error, RetryableChatbotError):
            return True
        if self.retry_on_timeout and is_transient_error(error):
            return True
        return False

    def _send_once(
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
        auth_type = self.auth.get("type")
        env_var_name = self.auth.get("env_var")
        if auth_type and env_var_name:
            auth_val = os.getenv(str(env_var_name))
            if auth_val:
                if auth_type == "bearer":
                    headers["Authorization"] = f"Bearer {auth_val}"
                    logger.debug("Authorization bearer header added")
                elif auth_type == "api_key":
                    header_name = self.auth.get("header_name", "x-api-key")
                    headers[header_name] = auth_val
                    logger.debug(f"API key header ({header_name}) added")
            else:
                logger.warning(f"Auth credential not found in environment variable: {env_var_name}")

        # Unified payload: support legacy params and config-driven parameters
        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "user_message": user_message,
            "query": user_message,
        }

        # Add Chatbot config if defined
        if self.chatbot_model or self.chatbot_temperature is not None or self.source_doc_ref:
            butler_config = {}
            if self.chatbot_model:
                butler_config["chatbot_model"] = self.chatbot_model
            if self.chatbot_temperature is not None:
                butler_config["chatbot_temperature"] = self.chatbot_temperature
            if self.source_doc_ref is not None:
                butler_config["source_document_reference"] = self.source_doc_ref
            payload["butler_11m_config"] = butler_config
            logger.debug(f"Chatbot config added: {butler_config}")

            # Default bmo_content if using Chatbot mode
            payload["bmo_content"] = ["Policies and Procedures"]
            logger.debug("Default bmo_content set to Policies and Procedures")

        if metadata:
            payload["metadata"] = metadata
            logger.debug(f"Metadata included in payload: {list(metadata.keys())}")

        logger.debug(f"Sending POST request with payload keys: {list(payload.keys())}")

        if not self.endpoint:
            raise ValueError("Chatbot endpoint is not configured")

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

            if self.retry_on_http_5xx and status_code in {429, 500, 502, 503, 504}:
                raise RetryableChatbotError(error, status_code=status_code)

        bot_text = extract_bot_text(body)
        if response.ok and _is_no_response_text(bot_text):
            raise RetryableChatbotError("target_empty_response", status_code=status_code)

        return ChatbotResponse.from_payload(body, latency_ms=round(latency_ms, 2), status_code=status_code,
                                            error=error)


def extract_bot_text(payload: dict[str, Any]) -> str:
    for key in ("response", "answer", "message", "content", "text", "llm_response"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return ""
