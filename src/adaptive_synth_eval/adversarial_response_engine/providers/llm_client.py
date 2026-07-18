import json
from typing import Dict, Any, Optional, Callable

from .llm_backends import LLMCallFn
from ..core.token_budget import TokenBudgetManager, TokenUsage


def _salvage_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Best-effort recovery of a JSON object from a messy/truncated LLM response.

    Handles three real-world cases seen from judge/planner models:
      1. JSON wrapped in ```fences``` or surrounded by prose.
      2. Trailing junk after a complete object.
      3. A single object truncated by max_tokens (unterminated string / missing
         closing braces) — we close it so the fields emitted before the cutoff
         (the scores, which the prompt now puts first) are still parsed.
    Returns the parsed dict, or None if nothing usable can be recovered.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    # Drop markdown fences anywhere (```json ... ``` or ``` ... ```).
    if "```" in text:
        fenced = text.split("```")
        # pick the longest fenced segment that looks like JSON
        cands = [seg for seg in fenced if "{" in seg]
        if cands:
            text = max(cands, key=len).strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()

    start = text.find("{")
    if start == -1:
        return None
    text = text[start:]

    # Fast path: a clean object (ignoring trailing junk).
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Repair a truncated object: close an open string, then balance braces.
    repaired = text
    if repaired.count('"') % 2 == 1:
        repaired += '"'
    open_braces = repaired.count("{") - repaired.count("}")
    if open_braces > 0:
        # strip a dangling ", key":  / trailing comma so the close is valid
        repaired = repaired.rstrip().rstrip(",")
        repaired += "}" * open_braces
    try:
        obj = json.loads(repaired)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        return None
    return None


class LLMClient:
    """
    Wraps an LLM backend callable, tracks token usage, and returns parsed JSON.

    The backend callable must return:
        {"content": "<json string>", "usage": {"prompt_tokens": int, "completion_tokens": int}}
    """

    def __init__(
            self,
            call_fn: LLMCallFn,
            budget: TokenBudgetManager,
            on_usage: Callable[[int, int], None] | None = None,
    ):
        self.call_fn = call_fn
        self.budget = budget
        self.on_usage = on_usage

    def complete_json(self, system: str, user: str) -> Dict[str, Any]:
        result = self.call_fn(system=system, user=user)

        usage = result.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        with self.budget._lock:
            self.budget.add(TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ))
            if self.on_usage is not None:
                self.on_usage(prompt_tokens, completion_tokens)

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
            # Best-effort salvage (prose-wrapped, trailing junk, or truncated output)
            # before declaring the response unparseable.
            salvaged = _salvage_json(raw)
            if salvaged is not None:
                return salvaged
            return {"error": "invalid_json", "raw": raw}
