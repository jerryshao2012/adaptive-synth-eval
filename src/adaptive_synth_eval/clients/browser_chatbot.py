from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable

from adaptive_synth_eval.clients.chatbot import ChatbotResponse
from adaptive_synth_eval.clients.logger_utils import setup_logger
from adaptive_synth_eval.config.schemas import BrowserChatbot

logger = setup_logger(__name__)


class BrowserChatbotClient:
    def __init__(
            self,
            *,
            browser_config: BrowserChatbot,
            enabled: bool = True,
            sync_playwright_factory: Callable[[], Any] | None = None,
    ):
        self.browser_config = browser_config
        self.enabled = enabled
        self._sync_playwright_factory = sync_playwright_factory
        self._playwright = None
        self._browser = None
        self._page = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser-chatbot")

    def send(
            self,
            *,
            conversation_id: str,
            session_id: str,
            turn_id: int,
            user_message: str,
            metadata: dict[str, Any] | None = None,
    ) -> ChatbotResponse:
        if not self.enabled:
            return ChatbotResponse.from_payload(
                {
                    "mock": True,
                    "response": f"[dry-run browser chatbot response for turn {turn_id}]",
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                },
                latency_ms=0.0,
                status_code=0,
            )

        start = time.perf_counter()
        try:
            page = self._ensure_page()
            before_count = page.locator(self.browser_config.response_selector).count()
            page.locator(self.browser_config.input_selector).fill(user_message)
            page.locator(self.browser_config.submit_selector).click()
            timeout_ms = self.browser_config.response_timeout_seconds * 1000
            page.wait_for_function(
                """
                ({selector, beforeCount}) => {
                    const nodes = document.querySelectorAll(selector);
                    return nodes.length > beforeCount && nodes[nodes.length - 1].innerText.trim().length > 0;
                }
                """,
                {"selector": self.browser_config.response_selector, "beforeCount": before_count},
                timeout=timeout_ms,
            )
            responses = page.locator(self.browser_config.response_selector)
            bot_text = responses.nth(responses.count() - 1).inner_text()
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            return ChatbotResponse.from_payload(
                {
                    "browser": True,
                    "response": bot_text,
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "metadata": metadata or {},
                },
                latency_ms=latency_ms,
                status_code=200,
            )
        except Exception as exc:
            logger.exception("Browser chatbot request failed: %s", exc)
            return ChatbotResponse.from_payload({}, latency_ms=None, status_code=0, error=str(exc))

    async def send_async(
            self,
            *,
            conversation_id: str,
            session_id: str,
            turn_id: int,
            user_message: str,
            metadata: dict[str, Any] | None = None,
    ) -> ChatbotResponse:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            partial(
                self.send,
                conversation_id=conversation_id,
                session_id=session_id,
                turn_id=turn_id,
                user_message=user_message,
                metadata=metadata,
            ),
        )

    async def close_async(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self.close)
        self._executor.shutdown(wait=True)

    def close(self) -> None:
        if self._browser:
            self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def _ensure_page(self):
        if self._page:
            return self._page

        playwright = self._start_playwright()
        launch_kwargs: dict[str, Any] = {"headless": self.browser_config.headless}
        if self.browser_config.browser_type == "edge":
            launch_kwargs["channel"] = "msedge"
        self._browser = playwright.chromium.launch(**launch_kwargs)
        self._page = self._browser.new_page()
        self._page.goto(self.browser_config.url, wait_until="domcontentloaded")
        ready_selector = self.browser_config.ready_selector or self.browser_config.input_selector
        self._page.wait_for_selector(ready_selector, timeout=self.browser_config.response_timeout_seconds * 1000)
        return self._page

    def _start_playwright(self):
        if self._playwright:
            return self._playwright

        if self._sync_playwright_factory is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "Browser mode requires the 'playwright' package. Install it with `uv sync`.") from exc
            self._sync_playwright_factory = sync_playwright

        self._playwright = self._sync_playwright_factory().start()
        return self._playwright
