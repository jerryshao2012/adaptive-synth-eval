"""Retry helpers for transient LLM API failures (429 / 500 / connection errors / timeouts).

We can't blanket-retry every exception type (some libs raise on auth/permission
errors that won't get better with retries). Match by class name + status code
substring so we don't pull anthropic/openai SDK types in here.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Match exception class names that are typically transient.
_TRANSIENT_EXCEPTION_NAMES = {
    "APITimeoutError", "APIConnectionError", "RateLimitError",
    "InternalServerError", "ServiceUnavailableError", "OverloadedError",
    "ReadTimeout", "ConnectTimeout", "ConnectionError",
    "Timeout", "TimeoutException",
}
# Substrings that suggest a transient HTTP status in the exception message.
_TRANSIENT_MESSAGE_SUBSTRINGS = ("429", "500", "502", "503", "504", "overloaded")


def is_transient(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in _TRANSIENT_EXCEPTION_NAMES:
        return True
    msg = str(exc).lower()
    return any(s in msg for s in _TRANSIENT_MESSAGE_SUBSTRINGS)


def retry_call(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    initial_backoff: float = 1.0,
    max_backoff: float = 30.0,
    label: str = "llm_call",
) -> T:
    """Call fn() with exponential backoff on transient failures."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if attempt >= max_attempts or not is_transient(exc):
                raise
            sleep_for = min(max_backoff, initial_backoff * (2 ** (attempt - 1)))
            sleep_for *= 0.7 + 0.6 * random.random()  # jitter
            logger.warning(
                "[%s] transient %s on attempt %d/%d (%s); retrying in %.2fs",
                label, type(exc).__name__, attempt, max_attempts, str(exc)[:120], sleep_for,
            )
            time.sleep(sleep_for)
