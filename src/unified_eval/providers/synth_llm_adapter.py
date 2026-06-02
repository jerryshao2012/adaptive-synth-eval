"""Adapter that wraps a SynthChatFn into something UserSimulator can use.

UserSimulator only requires:
- .enabled: bool
- .model_provider: str | None
- .complete(prompt: str) -> LLMResult-like (.content, .error, .raw)

When a BudgetMeter is provided, we estimate prompt + completion token counts from
word counts (no real tokenizer; rough but consistent with ARE's mock backend) so
synth-side usage participates in the unified budget.
"""
from __future__ import annotations

from dataclasses import dataclass

from unified_eval.providers.llm_factory import SynthChatFn


@dataclass
class _Result:
    content: str
    raw: dict
    error: str | None = None


def _estimate_tokens(text: str) -> int:
    # Rough heuristic: 1 token ≈ 0.75 words. Good enough for budget bookkeeping
    # when the provider doesn't surface token usage via LangChain.
    return int(len(text.split()) / 0.75) if text else 0


class SynthLLMAdapter:
    """Minimal duck-typed substitute for adaptive_synth_eval.clients.llm.LLMClient."""

    def __init__(
            self,
            synth_chat: SynthChatFn,
            provider_label: str,
            meter=None,  # BudgetMeter | None
            component_label: str = "user_simulator",
            model: str = "unknown",
    ):
        self._synth_chat = synth_chat
        self.enabled = True
        self.model_provider = provider_label
        self.meter = meter
        self.component_label = component_label
        if meter is not None:
            meter.register(component_label, model)

    def complete(self, prompt: str):
        try:
            content = self._synth_chat(prompt)
            content_str = str(content)
            if self.meter is not None:
                self.meter.record(
                    self.component_label,
                    _estimate_tokens(prompt),
                    _estimate_tokens(content_str),
                )
            return _Result(content=content_str, raw={"provider": self.model_provider}, error=None)
        except Exception as exc:  # noqa: BLE001
            return _Result(
                content="",
                raw={"provider": self.model_provider, "exception": type(exc).__name__},
                error=f"{type(exc).__name__}: {exc}",
            )
