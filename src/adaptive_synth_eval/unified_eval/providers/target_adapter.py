"""Thin wrapper over ASE's chatbot factory.

ASE's ChatbotClient already exposes send_async(), and BrowserChatbotClient
likewise. We re-export create_chatbot_client so unified_eval has a single
target import path. No async/sync glue needed.
"""
from __future__ import annotations

from adaptive_synth_eval.clients.chatbot_factory import create_chatbot_client

__all__ = ["create_chatbot_client"]
