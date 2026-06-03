from __future__ import annotations

import asyncio
import json
import time
import uuid
from threading import Lock
from typing import Any

from adaptive_synth_eval.clients.chatbot import ChatbotResponse
from adaptive_synth_eval.clients.logger_utils import setup_logger
from adaptive_synth_eval.clients.retry_utils import is_transient_error, retry_on_exception

logger = setup_logger(__name__)

_MIN_RUNTIME_SESSION_ID_LEN = 33


class AgentCoreChatbotClient:
    def __init__(
            self,
            *,
            enabled: bool = True,
            region: str = "us-east-1",
            agent_runtime_arn: str | None = None,
            qualifier: str | None = None,
            payload_prompt_key: str = "prompt",
            runtime_session_id_prefix: str = "ase_",
            retry_max_retries: int | None = None,
            retry_initial_backoff: float | None = None,
            retry_max_backoff: float | None = None,
            retry_backoff_multiplier: float | None = None,
            retry_jitter: bool | None = None,
    ):
        self.enabled = enabled
        self.region = region
        self.agent_runtime_arn = agent_runtime_arn
        self.qualifier = qualifier
        self.payload_prompt_key = payload_prompt_key
        self.runtime_session_id_prefix = runtime_session_id_prefix

        self._runtime_session_ids: dict[str, str] = {}
        self._runtime_session_lock = Lock()
        self._client = None

        self._invoke_with_retry = retry_on_exception(
            self._invoke_once,
            max_retries=retry_max_retries,
            initial_backoff=retry_initial_backoff,
            max_backoff=retry_max_backoff,
            backoff_multiplier=retry_backoff_multiplier,
            jitter=retry_jitter,
            should_retry=self._is_retryable_agentcore_error,
            retry_label="AgentCore transient",
        )

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.enabled:
            return None
        try:
            import boto3
        except ImportError as exc:
            raise ImportError("Install boto3 to use target.mode=agentcore") from exc
        self._client = boto3.client("bedrock-agentcore", region_name=self.region)
        return self._client

    def _is_retryable_agentcore_error(self, error: Exception) -> bool:
        if is_transient_error(error):
            return True

        # Keep provider-specific matching string-based to avoid importing botocore.
        text = str(error).lower()
        retryable_markers = [
            "throttl",
            "too many requests",
            "service unavailable",
            "internalserver",
            "internal server",
            "request timeout",
            "temporarily unavailable",
        ]
        return any(marker in text for marker in retryable_markers)

    def _runtime_session_id_for(self, conversation_id: str, session_id: str) -> str:
        key = f"{conversation_id}:{session_id}"
        with self._runtime_session_lock:
            cached = self._runtime_session_ids.get(key)
            if cached:
                return cached

            digest = uuid.uuid5(uuid.NAMESPACE_DNS, key).hex
            candidate = f"{self.runtime_session_id_prefix}{digest}"
            if len(candidate) < _MIN_RUNTIME_SESSION_ID_LEN:
                candidate = f"{candidate}{'0' * (_MIN_RUNTIME_SESSION_ID_LEN - len(candidate))}"
            self._runtime_session_ids[key] = candidate
            return candidate

    def _invoke_once(
            self,
            *,
            conversation_id: str,
            session_id: str,
            user_message: str,
    ) -> tuple[dict[str, Any], int, float]:
        client = self._get_client()
        runtime_session_id = self._runtime_session_id_for(conversation_id, session_id)
        payload = json.dumps({self.payload_prompt_key: user_message})

        request: dict[str, Any] = {
            "agentRuntimeArn": self.agent_runtime_arn,
            "runtimeSessionId": runtime_session_id,
            "payload": payload,
        }
        if self.qualifier:
            request["qualifier"] = self.qualifier

        start = time.perf_counter()
        response = client.invoke_agent_runtime(**request)
        latency_ms = (time.perf_counter() - start) * 1000

        raw_stream = response["response"].read()
        if isinstance(raw_stream, bytes):
            raw_text = raw_stream.decode("utf-8")
        else:
            raw_text = str(raw_stream)

        body: dict[str, Any]
        try:
            parsed = json.loads(raw_text)
            body = parsed if isinstance(parsed, dict) else {"response": str(parsed)}
        except json.JSONDecodeError:
            body = {"response": raw_text}

        response_meta = response.get("ResponseMetadata", {})
        status_code = int(response_meta.get("HTTPStatusCode", 200))
        return body, status_code, latency_ms

    def send(
            self,
            *,
            conversation_id: str,
            session_id: str,
            turn_id: int,
            user_message: str,
            metadata: dict[str, Any] | None = None,
    ) -> ChatbotResponse:
        if not self.enabled:
            return ChatbotResponse.from_payload(
                {
                    "mock": True,
                    "response": f"[dry-run agentcore response for turn {turn_id}]",
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                },
                latency_ms=0.0,
                status_code=0,
            )

        if not self.agent_runtime_arn:
            error = "AgentCore runtime ARN is not configured"
            return ChatbotResponse.from_payload({}, latency_ms=None, status_code=0, error=error)

        try:
            body, status_code, latency_ms = self._invoke_with_retry(
                conversation_id=conversation_id,
                session_id=session_id,
                user_message=user_message,
            )
            error = None if 200 <= status_code < 300 else f"HTTP {status_code}"
            return ChatbotResponse.from_payload(
                body,
                latency_ms=round(latency_ms, 2),
                status_code=status_code,
                error=error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("AgentCore invocation failed: %s", exc)
            return ChatbotResponse.from_payload(
                {},
                latency_ms=None,
                status_code=0,
                error=f"{type(exc).__name__}: {exc}",
            )

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

    def close(self) -> None:
        self._runtime_session_ids.clear()
