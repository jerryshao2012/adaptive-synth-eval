"""Trajectory trace acquisition for trajectory-aware evaluation.

The target multi-agent system embeds a structured execution `trace` in its JSON
response body. Because the chatbot clients preserve the full response payload in
`ChatbotResponse.raw`, the trace is captured for free — `InlineTraceProvider`
just reads and normalizes it.

Kept as a small class (rather than a bare function) so a future log-store-backed
provider (CloudWatch/X-Ray/S3) could slot in behind the same `fetch` shape without
touching the engine. Only the inline provider exists today.
"""
from __future__ import annotations

from typing import Any, Dict


def normalize_trace(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    """Coerce a raw trace dict into the canonical trajectory schema.

    Defensive passthrough: tolerates a missing/partial/None trace and never
    raises, so a target that omits the trace (or emits a malformed one) degrades
    to an empty-but-valid trajectory rather than breaking the turn.
    """
    trace = raw if isinstance(raw, dict) else {}

    def _list(key: str) -> list:
        value = trace.get(key, [])
        return value if isinstance(value, list) else []

    return {
        "agents_called": _list("agents_called"),
        "handoffs": _list("handoffs"),
        "tool_calls": _list("tool_calls"),
        "retrieved_items": _list("retrieved_items"),
        "memory_reads": _list("memory_reads"),
        "memory_writes": _list("memory_writes"),
        "errors": _list("errors"),
        "latency_ms": trace.get("latency_ms"),
        "raw_trace": trace.get("raw_trace", trace),
    }


def compact_trace(trace: Dict[str, Any]) -> Dict[str, Any]:
    """Cheap, deterministic summary of a normalized trace — no LLM required.

    Useful as a fallback when the LLM TraceSummarizer is unavailable and for
    quick scanning in logs/metrics.
    """
    return {
        "agents_called_count": len(trace.get("agents_called", [])),
        "agents_called": trace.get("agents_called", [])[:10],
        "handoff_count": len(trace.get("handoffs", [])),
        "tool_call_count": len(trace.get("tool_calls", [])),
        "memory_write_count": len(trace.get("memory_writes", [])),
        "memory_read_count": len(trace.get("memory_reads", [])),
        "retrieved_item_count": len(trace.get("retrieved_items", [])),
        "error_count": len(trace.get("errors", [])),
        "latency_ms": trace.get("latency_ms"),
    }


class InlineTraceProvider:
    """Extracts the execution trace embedded inline in the target's response body.

    `trace_field` is the key in the response payload that holds the trace
    (defaults to "trace"). Returns a normalized (possibly empty) trace.
    """

    def __init__(self, trace_field: str = "trace"):
        self.trace_field = trace_field

    def fetch(self, response_raw: Dict[str, Any] | None) -> Dict[str, Any]:
        payload = response_raw if isinstance(response_raw, dict) else {}
        return normalize_trace(payload.get(self.trace_field, {}))
