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

    # How many times to re-call the backend when it returns content that does not
    # parse as JSON. A weak model occasionally emits prose or truncated JSON; one or
    # two re-rolls almost always recovers a clean object. Each attempt is charged to
    # the token budget. Only invalid JSON is retried here — transient API errors are
    # retried lower down in the backend (see providers/retry.py).
    _max_json_attempts: int = 3

    def __init__(self, call_fn: LLMCallFn, budget: TokenBudgetManager):
        self.call_fn = call_fn
        self.budget = budget

    def complete_json(self, system: str, user: str) -> Dict[str, Any]:
        last_raw: Any = "{}"
        for _ in range(self._max_json_attempts):
            result = self.call_fn(system=system, user=user)

            usage = result.get("usage", {})
            self.budget.add(TokenUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ))

            raw = result.get("content", "{}")
            last_raw = raw
            if raw is None:
                continue
            # Strip markdown code fences that LLMs sometimes wrap JSON in
            stripped = raw.strip()
            if stripped.startswith("```"):
                stripped = stripped.split("\n", 1)[-1]
                stripped = stripped.rsplit("```", 1)[0].strip()
            try:
                return json.loads(stripped)
            except (json.JSONDecodeError, TypeError):
                continue  # re-roll: ask the model again for valid JSON

        # All attempts produced unparseable output — surface it so callers can count
        # it as a real error instead of silently degrading to a fallback.
        return {"error": "invalid_json", "raw": last_raw}
