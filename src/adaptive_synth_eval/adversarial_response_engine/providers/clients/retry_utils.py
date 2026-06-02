"""Retry utilities for handling rate limits and transient errors."""
# Sibling copy exists at adaptive_synth_eval/clients/retry_utils.py — keep in sync manually.

from __future__ import annotations

import asyncio
import os
import time
from functools import wraps
from typing import Any, Callable, List, Tuple, TypeVar

from dotenv import load_dotenv

from .logger_utils import setup_logger

load_dotenv()

logger = setup_logger(__name__)

MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "5"))
INITIAL_BACKOFF = float(os.getenv("MODEL_INITIAL_BACKOFF", "1.0"))
MAX_BACKOFF = float(os.getenv("MODEL_MAX_BACKOFF", "60.0"))
BACKOFF_MULTIPLIER = float(os.getenv("MODEL_BACKOFF_MULTIPLIER", "2.0"))

T = TypeVar("T")


def _str2bool(v, default=None):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    if v.lower() in ("no", "false", "f", "n", "0"):
        return False
    return default


JITTER_ENABLED = _str2bool(os.getenv("MODEL_RETRY_JITTER", "true"), True)
MODEL_TPM = int(os.getenv("MODEL_TPM", "120000"))
MODEL_RPM = int(os.getenv("MODEL_RPM", "500"))


def is_rate_limit_error(error: Exception) -> bool:
    error_str = str(error).lower()
    if any(m in error_str for m in ["content filter", "content_filter", "responsibleai"]):
        return False
    return any(
        indicator in error_str
        for indicator in [
            "rate limit", "rate_limit", "ratelimit", "too many requests", "429",
            "throttl", "quota exceeded", "usage limit", "request limit",
            "calls per minute", "tokens per minute", "requests per minute",
        ]
    )


def calculate_backoff(attempt: int, initial: float, max_wait: float, multiplier: float, jitter: bool) -> float:
    backoff = min(initial * (multiplier ** attempt), max_wait)
    if jitter:
        import random
        backoff = backoff * (0.5 + random.random() * 0.5)
    return backoff


def retry_on_rate_limit(
        func: Callable[..., T] | None = None,
        *,
        max_retries: int | None = None,
        initial_backoff: float | None = None,
        max_backoff: float | None = None,
        backoff_multiplier: float | None = None,
        jitter: bool | None = None,
) -> Callable[..., T]:
    retries = max_retries if max_retries is not None else MAX_RETRIES
    init_backoff = initial_backoff if initial_backoff is not None else INITIAL_BACKOFF
    max_bo = max_backoff if max_backoff is not None else MAX_BACKOFF
    mult = backoff_multiplier if backoff_multiplier is not None else BACKOFF_MULTIPLIER
    jit = jitter if jitter is not None else JITTER_ENABLED

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None
            for attempt in range(retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if not is_rate_limit_error(e):
                        raise
                    if attempt >= retries:
                        raise
                    backoff_time = calculate_backoff(attempt, init_backoff, max_bo, mult, jit)
                    logger.warning(
                        f"Rate limit hit in {fn.__name__} (attempt {attempt + 1}/{retries + 1}). "
                        f"Retrying in {backoff_time:.2f}s..."
                    )
                    time.sleep(backoff_time)
            raise last_exception  # type: ignore[misc]

        @wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None
            for attempt in range(retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if not is_rate_limit_error(e):
                        raise
                    if attempt >= retries:
                        raise
                    backoff_time = calculate_backoff(attempt, init_backoff, max_bo, mult, jit)
                    logger.warning(
                        f"Rate limit hit in {fn.__name__} (attempt {attempt + 1}/{retries + 1}). "
                        f"Retrying in {backoff_time:.2f}s..."
                    )
                    await asyncio.sleep(backoff_time)
            raise last_exception  # type: ignore[misc]

        import inspect
        if inspect.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


class AsyncRateLimiter:
    """Proactive rate shaping to avoid 429s (TPM + RPM)."""

    def __init__(self, tpm: int, rpm: int, safe_margin: float = 0.8):
        self.safe_tpm = int(tpm * safe_margin)
        self.min_interval = 60.0 / (rpm * safe_margin)
        self.window_seconds = 60.0
        self.token_window: List[Tuple[float, int]] = []
        self.last_request_time = 0.0
        self.lock = asyncio.Lock()
        try:
            import tiktoken
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.tokenizer = None

    def estimate_tokens(self, prompt: str, max_tokens: int) -> int:
        if self.tokenizer:
            prompt_tokens = len(self.tokenizer.encode(prompt))
        else:
            prompt_tokens = int(len(prompt) / 4)
        return prompt_tokens + max_tokens

    async def wait_for_capacity(self, estimated_tokens: int) -> None:
        async with self.lock:
            while True:
                now = time.time()
                self.token_window = [
                    (t, tok) for (t, tok) in self.token_window
                    if now - t < self.window_seconds
                ]
                used_tokens = sum(tok for _, tok in self.token_window)
                elapsed = now - self.last_request_time
                if used_tokens + estimated_tokens <= self.safe_tpm and (
                        self.last_request_time == 0.0 or elapsed >= self.min_interval):
                    self.token_window.append((now, estimated_tokens))
                    self.last_request_time = now
                    return
                sleep_time = max(0.1, self.min_interval - elapsed)
                await asyncio.sleep(sleep_time)
