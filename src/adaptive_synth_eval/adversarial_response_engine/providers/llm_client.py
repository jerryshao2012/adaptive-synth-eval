import json
from typing import Dict, Any

from .llm_backends import LLMCallFn
from ..core.token_budget import TokenBudgetManager, TokenUsage


class LLMClient:
    """
    Wraps an LLM backend callable, tracks token usage, and returns parsed JSON.

    The backend callable must return:
        {"content": "<json string>", "usage": {"prompt_tokens": int, "completion_tokens": int}}
    """

    def __init__(self, call_fn: LLMCallFn, budget: TokenBudgetManager):
        self.call_fn = call_fn
        self.budget = budget

    def complete_json(self, system: str, user: str) -> Dict[str, Any]:
        result = self.call_fn(system=system, user=user)

        usage = result.get("usage", {})
        self.budget.add(TokenUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        ))

        raw = result.get("content", "{}")
        if raw is None:
            return {"error": "invalid_json", "raw": None}
        # Strip markdown code fences that LLMs sometimes wrap JSON in
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            stripped = stripped.rsplit("```", 1)[0].strip()
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            return {"error": "invalid_json", "raw": raw}
