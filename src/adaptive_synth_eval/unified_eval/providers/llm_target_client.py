"""Target chatbot driven by a Claude (Anthropic) LLM.

Maintains a per-conversation message history so the bot has full context for each
turn. Exposes send() and send_async() with the same shape as ASE's ChatbotClient
so the orchestrator doesn't care which backend it's talking to.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from adaptive_synth_eval.clients.chatbot import ChatbotResponse
from adaptive_synth_eval.unified_eval.config.schemas import LLMSpec
from adaptive_synth_eval.clients.retry_utils import retry_call


class LLMTargetClient:
    """Claude-as-target chatbot. One client per run, conversation-keyed history."""

    def __init__(
            self,
            spec: LLMSpec,
            system_prompt: str,
            dry_run: bool = False,
            meter=None,  # BudgetMeter | None
            component_label: str = "target_bot",
            retry_max_attempts: int = 3,
            retry_initial_backoff: float = 1.0,
            retry_max_backoff: float = 30.0,
    ):
        self.spec = spec
        self.system_prompt = system_prompt or "You are a helpful assistant."
        self.dry_run = dry_run
        self.meter = meter
        self.component_label = component_label
        self.retry_max_attempts = retry_max_attempts
        self.retry_initial_backoff = retry_initial_backoff
        self.retry_max_backoff = retry_max_backoff
        self._client = None
        self._histories: dict[str, list[dict[str, str]]] = {}
        if meter is not None:
            meter.register(component_label, spec.model or "unknown")

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self.dry_run:
            return None
        provider = self.spec.provider.lower()
        if provider == "claude":
            try:
                import anthropic
            except ImportError as exc:
                raise ImportError("Install anthropic: pip install anthropic") from exc
            api_key = os.environ.get(self.spec.api_key_env or "ANTHROPIC_API_KEY")
            self._client = anthropic.Anthropic(api_key=api_key)
        else:
            raise ValueError(
                f"LLMTargetClient currently supports provider 'claude' only "
                f"(got {self.spec.provider!r}). Extend providers/llm_target_client.py "
                "to support other providers."
            )
        return self._client

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
                {"mock": True, "response": f"[dry-run claude-target reply for turn {turn_id}]"},
                latency_ms=0.0,
                status_code=0,
            )

        history = self._histories.setdefault(conversation_id, [])
        history.append({"role": "user", "content": user_message})
        client = self._get_client()
        start = time.perf_counter()
        try:
            response = retry_call(
                lambda: client.messages.create(
                    model=self.spec.model or "claude-haiku-4-5-20251001",
                    max_tokens=self.spec.max_tokens,
                    system=self.system_prompt,
                    messages=history,
                ),
                max_attempts=self.retry_max_attempts,
                initial_backoff=self.retry_initial_backoff,
                max_backoff=self.retry_max_backoff,
                label=self.component_label,
            )
            text = response.content[0].text if response.content else ""
            history.append({"role": "assistant", "content": text})
            input_tokens = int(getattr(response.usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(response.usage, "output_tokens", 0) or 0)
            if self.meter is not None:
                self.meter.record(self.component_label, input_tokens, output_tokens)
            latency_ms = (time.perf_counter() - start) * 1000
            payload = {
                "response": text,
                "model": self.spec.model,
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            }
            return ChatbotResponse.from_payload(
                payload, latency_ms=latency_ms, status_code=200,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - start) * 1000
            return ChatbotResponse.from_payload(
                {"error": str(exc)},
                latency_ms=latency_ms,
                status_code=0,
                error=f"{type(exc).__name__}: {exc}",
            )

    def drop_conversation(self, conversation_id: str) -> None:
        """Forget per-conversation history so memory doesn't grow unbounded across a run."""
        self._histories.pop(conversation_id, None)

    async def send_async(self, **kwargs) -> ChatbotResponse:
        return await asyncio.to_thread(self.send, **kwargs)

    def close(self) -> None:
        self._histories.clear()
