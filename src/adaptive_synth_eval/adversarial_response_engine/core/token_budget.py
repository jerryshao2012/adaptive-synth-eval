import threading
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
        self.reserved_tokens = 0
        self._reservations: dict[str, int] = {}
        self._lock = threading.RLock()

    @property
    def used_total_tokens(self) -> int:
        with self._lock:
            return self.used_prompt_tokens + self.used_completion_tokens

    @property
    def remaining_tokens(self) -> int:
        with self._lock:
            return self.max_total_tokens - self.used_prompt_tokens - self.used_completion_tokens

    def can_continue(self, reserve_tokens: int = 1000) -> bool:
        with self._lock:
            available = (
                    self.max_total_tokens
                    - self.used_prompt_tokens
                    - self.used_completion_tokens
                    - self.reserved_tokens
            )
            return available >= reserve_tokens

    def try_reserve(self, reserve_tokens: int = 1000) -> bool:
        reserve_tokens = max(0, int(reserve_tokens))
        with self._lock:
            available = (
                    self.max_total_tokens
                    - self.used_prompt_tokens
                    - self.used_completion_tokens
                    - self.reserved_tokens
            )
            if available < reserve_tokens:
                return False
            self.reserved_tokens += reserve_tokens
            return True

    def release_reservation(self, reserve_tokens: int = 1000) -> None:
        reserve_tokens = max(0, int(reserve_tokens))
        with self._lock:
            self.reserved_tokens = max(0, self.reserved_tokens - reserve_tokens)

    def try_reserve_for(self, owner: str, reserve_tokens: int = 1000) -> bool:
        reserve_tokens = max(0, int(reserve_tokens))
        with self._lock:
            if owner in self._reservations:
                return True
            available = (
                    self.max_total_tokens
                    - self.used_prompt_tokens
                    - self.used_completion_tokens
                    - self.reserved_tokens
            )
            if available < reserve_tokens:
                return False
            self._reservations[owner] = reserve_tokens
            self.reserved_tokens += reserve_tokens
            return True

    def release_reservation_for(self, owner: str) -> None:
        with self._lock:
            amount = self._reservations.pop(owner, 0)
            self.reserved_tokens = max(0, self.reserved_tokens - amount)

    def release_reservations_for_prefix(self, prefix: str) -> None:
        with self._lock:
            owners = [owner for owner in self._reservations if owner.startswith(prefix)]
            for owner in owners:
                self.reserved_tokens -= self._reservations.pop(owner)
            self.reserved_tokens = max(0, self.reserved_tokens)

    def add(self, usage: TokenUsage) -> None:
        with self._lock:
            self.used_prompt_tokens += int(usage.prompt_tokens or 0)
            self.used_completion_tokens += int(usage.completion_tokens or 0)

    def snapshot(self) -> dict[str, int]:
        """Persist actual spend only; reservations are deliberately transient."""
        with self._lock:
            return {
                "max_total_tokens": self.max_total_tokens,
                "used_prompt_tokens": self.used_prompt_tokens,
                "used_completion_tokens": self.used_completion_tokens,
            }

    def restore_usage(self, payload: dict) -> None:
        with self._lock:
            self.used_prompt_tokens = int(payload.get("used_prompt_tokens", 0) or 0)
            self.used_completion_tokens = int(payload.get("used_completion_tokens", 0) or 0)
            self.reserved_tokens = 0
            self._reservations.clear()

    def reset(self) -> None:
        with self._lock:
            self.used_prompt_tokens = 0
            self.used_completion_tokens = 0
            self.reserved_tokens = 0
            self._reservations.clear()
