from __future__ import annotations

from adaptive_synth_eval.clients.browser_chatbot import BrowserChatbotClient
from adaptive_synth_eval.clients.chatbot import ChatbotClient
from adaptive_synth_eval.config.schemas import TargetChatbot


def create_chatbot_client(config: TargetChatbot, *, dry_run: bool = False):
    enabled = config.enabled and not dry_run
    if config.mode == "browser":
        if config.browser is None:
            raise ValueError("target_chatbot.browser is required when target_chatbot.mode is 'browser'")
        return BrowserChatbotClient(browser_config=config.browser, enabled=enabled)

    return ChatbotClient(
        endpoint=config.endpoint,
        enabled=enabled,
        auth=config.auth,
        timeout_seconds=config.timeout_seconds,
    )
