"""Target chatbot backed by a deployed Amazon Bedrock AgentCore Runtime.

Unlike the HTTP `ChatbotClient` (which POSTs to a URL), a deployed AgentCore runtime
is invoked by ARN through the `bedrock-agentcore` SDK with SigV4/IAM auth. The agent
keeps per-conversation memory keyed by `runtimeSessionId`, so we derive a stable id
from conversation_id and send only the current turn each call.

Exposes send()/send_async() with the same shape as ASE's ChatbotClient so the
orchestrator doesn't care which backend it's talking to.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

from adaptive_synth_eval.clients.chatbot import ChatbotResponse

from unified_eval.config.schemas import TargetChatbot
from unified_eval.providers.retry import retry_call

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATE: dict[str, Any] = {"prompt": "{{user_message}}"}
_PLACEHOLDER = "{{user_message}}"


def _new_traceparent() -> str:
    """W3C traceparent header so each invoke is a correlatable trace in AgentCore
    Observability / CloudWatch: version-traceid(32 hex)-spanid(16 hex)-sampled."""
    return f"00-{uuid.uuid4().hex}-{uuid.uuid4().hex[:16]}-01"


def _substitute(node: Any, user_message: str) -> Any:
    """Deep-copy `node`, replacing the {{user_message}} placeholder in any string."""
    if isinstance(node, str):
        return node.replace(_PLACEHOLDER, user_message)
    if isinstance(node, dict):
        return {k: _substitute(v, user_message) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, user_message) for v in node]
    return node


def _join_sse(raw: str) -> str:
    """Concatenate the text deltas of a text/event-stream response.

    Each `data:` line is usually a JSON-encoded string fragment (e.g. data: "Hello "),
    so decode each chunk before joining — concatenating the raw lines would leave the
    surrounding quotes in place and garble word boundaries into `""`.
    """
    parts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[len("data:"):].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            decoded = json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            parts.append(chunk)          # not JSON — take the literal payload
            continue
        if isinstance(decoded, str):
            parts.append(decoded)
        elif isinstance(decoded, dict):  # structured event — best-effort text delta
            text = next(
                (decoded[k] for k in ("text", "delta", "content", "output", "response", "answer")
                 if isinstance(decoded.get(k), str)),
                None,
            )
            parts.append(text if text is not None else json.dumps(decoded))
        else:
            parts.append(str(decoded))
    return "".join(parts)


def _coerce(raw: str) -> dict[str, Any]:
    """Parse a response body string into a dict; wrap plain text under "text"."""
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"text": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"text": parsed if isinstance(parsed, str) else json.dumps(parsed)}


def _resolve_path(data: Any, path: str) -> Any:
    cur = data
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


class AgentCoreTargetClient:
    """Deployed-AgentCore-as-target chatbot. One client per run; session-aware."""

    def __init__(
        self,
        config: TargetChatbot,
        *,
        dry_run: bool = False,
        retry_max_attempts: int = 3,
        retry_initial_backoff: float = 1.0,
        retry_max_backoff: float = 30.0,
    ):
        self.dry_run = dry_run
        self.arn = config.agent_runtime_arn
        self.region = config.region or os.environ.get("AWS_REGION") or os.environ.get(
            "AWS_DEFAULT_REGION", "us-east-1"
        )
        self.qualifier = config.qualifier or "DEFAULT"
        self.request_template = config.request_template or _DEFAULT_TEMPLATE
        self.response_key_path = config.response_key_path
        self.timeout_seconds = config.timeout_seconds
        self.retry_max_attempts = retry_max_attempts
        self.retry_initial_backoff = retry_initial_backoff
        self.retry_max_backoff = retry_max_backoff
        self._client = None
        if not dry_run and not self.arn:
            raise ValueError(
                "target.mode == 'agentcore' requires target.agent_runtime_arn "
                "(set it in the contract or via ${AGENTCORE_RUNTIME_ARN})."
            )

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise ImportError("Install boto3: pip install boto3") from exc
        cfg = Config(
            read_timeout=self.timeout_seconds,
            connect_timeout=min(self.timeout_seconds, 10.0),
            retries={"max_attempts": 0},  # we own retries via retry_call
        )
        self._client = boto3.client("bedrock-agentcore", region_name=self.region, config=cfg)
        return self._client

    @staticmethod
    def _session_id(conversation_id: str) -> str:
        # AgentCore requires runtimeSessionId to be 33-256 chars.
        return f"{conversation_id}-agentcore".ljust(33, "0")[:256]

    def _read_response(self, resp: dict[str, Any]) -> dict[str, Any]:
        content_type = (resp.get("contentType") or "").lower()
        body = resp.get("response")
        raw = body.read() if hasattr(body, "read") else body
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if not isinstance(raw, str):
            raw = json.dumps(raw)
        if "text/event-stream" in content_type:
            raw = _join_sse(raw)
        return _coerce(raw)

    def send(
        self,
        *,
        conversation_id: str,
        session_id: str,
        turn_id: int,
        user_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> ChatbotResponse:
        if self.dry_run:
            return ChatbotResponse.from_payload(
                {"mock": True, "response": f"[dry-run agentcore reply for turn {turn_id}]"},
                latency_ms=0.0,
                status_code=0,
            )

        client = self._get_client()
        payload = json.dumps(_substitute(self.request_template, user_message)).encode("utf-8")
        trace_parent = _new_traceparent()
        start = time.perf_counter()
        try:
            resp = retry_call(
                lambda: client.invoke_agent_runtime(
                    agentRuntimeArn=self.arn,
                    runtimeSessionId=self._session_id(conversation_id),
                    qualifier=self.qualifier,
                    traceParent=trace_parent,
                    payload=payload,
                ),
                max_attempts=self.retry_max_attempts,
                initial_backoff=self.retry_initial_backoff,
                max_backoff=self.retry_max_backoff,
                label="agentcore_target",
            )
            trace_id = resp.get("traceId")
            logger.info(
                "agentcore invoke conv=%s turn=%s traceId=%s traceParent=%s",
                conversation_id, turn_id, trace_id, trace_parent,
            )
            parsed = self._read_response(resp)
            if self.response_key_path:
                value = _resolve_path(parsed, self.response_key_path)
                text = "" if value is None else (
                    value if isinstance(value, str) else json.dumps(value)
                )
                out_payload = dict(parsed)
                out_payload["response"] = text  # ensure from_payload extracts it
            else:
                out_payload = parsed
            if trace_id and isinstance(out_payload, dict):
                out_payload.setdefault("trace_id", trace_id)  # surfaced in response.raw
            latency_ms = (time.perf_counter() - start) * 1000
            return ChatbotResponse.from_payload(
                out_payload, latency_ms=round(latency_ms, 2), status_code=200,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - start) * 1000
            return ChatbotResponse.from_payload(
                {"error": str(exc)},
                latency_ms=round(latency_ms, 2),
                status_code=0,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def send_async(self, **kwargs) -> ChatbotResponse:
        return await asyncio.to_thread(self.send, **kwargs)

    def drop_conversation(self, conversation_id: str) -> None:
        # Session-aware on the agent side; nothing to forget locally.
        pass

    def close(self) -> None:
        pass
