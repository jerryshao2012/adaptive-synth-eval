from dataclasses import dataclass


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class TokenBudgetManager:
    """Tracks total experiment token usage. Experiment stops when budget is exhausted."""

    def __init__(self, max_total_tokens: int):
        self.max_total_tokens = max_total_tokens
        self.used_prompt_tokens = 0
        self.used_completion_tokens = 0

    @property
    def used_total_tokens(self) -> int:
        return self.used_prompt_tokens + self.used_completion_tokens

    @property
    def remaining_tokens(self) -> int:
        return self.max_total_tokens - self.used_total_tokens

    def can_continue(self, reserve_tokens: int = 1000) -> bool:
        return self.remaining_tokens >= reserve_tokens

    def add(self, usage: TokenUsage) -> None:
        self.used_prompt_tokens += usage.prompt_tokens
        self.used_completion_tokens += usage.completion_tokens

    def reset(self) -> None:
        self.used_prompt_tokens = 0
        self.used_completion_tokens = 0
