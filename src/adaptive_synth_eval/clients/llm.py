from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMResult:
    content: str
    raw: dict[str, Any]
    error: str | None = None


class LLMClient:
    """Small placeholder client for optional local judging/generation hooks."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def complete(self, prompt: str) -> LLMResult:
        if not self.enabled:
            return LLMResult(content="", raw={"mock": True, "prompt": prompt}, error="llm_disabled")
        raise NotImplementedError("Configure an approved LLM provider before enabling LLMClient")
