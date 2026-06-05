from __future__ import annotations

from adaptive_synth_eval.clients.agentcore_chatbot import AgentCoreChatbotClient
from adaptive_synth_eval.clients.browser_chatbot import BrowserChatbotClient
from adaptive_synth_eval.clients.chatbot import ChatbotClient
from adaptive_synth_eval.config.schemas import TargetChatbot


def create_chatbot_client(config: TargetChatbot, *, dry_run: bool = False, max_concurrency: int | None = None):
    enabled = config.enabled and not dry_run
    if config.mode == "browser":

        if config.browser is None:
            raise ValueError("target.browser is required when target.mode is 'browser'")
        return BrowserChatbotClient(browser_config=config.browser, enabled=enabled)

    if config.mode == "agentcore":
        if config.agentcore is None:
            raise ValueError(
                "target.agentcore is required when target.mode is 'agentcore' "
                "(nest region/agent_runtime_arn/qualifier under target.agentcore)."
            )
        ac = config.agentcore
        # Give the boto3 HTTP pool a little headroom over the worker concurrency.
        pool = max(10, (max_concurrency or 1) + 4)
        return AgentCoreChatbotClient(
            enabled=enabled,
            region=ac.region,
            agent_runtime_arn=ac.agent_runtime_arn,
            qualifier=ac.qualifier,
            payload_prompt_key=ac.payload_prompt_key,
            runtime_session_id_prefix=ac.runtime_session_id_prefix,
            retry_max_retries=config.retry_max_retries,
            retry_initial_backoff=config.retry_initial_backoff_seconds,
            retry_max_backoff=config.retry_max_backoff_seconds,
            retry_backoff_multiplier=config.retry_backoff_multiplier,
            retry_jitter=config.retry_jitter,
            max_pool_connections=pool,
        )

    return ChatbotClient(
        endpoint=config.endpoint,
        enabled=enabled,
        auth=config.auth,
        timeout_seconds=config.timeout_seconds,
        retry_max_retries=config.retry_max_retries,
        retry_initial_backoff=config.retry_initial_backoff_seconds,
        retry_max_backoff=config.retry_max_backoff_seconds,
        retry_backoff_multiplier=config.retry_backoff_multiplier,
        retry_jitter=config.retry_jitter,
        retry_on_timeout=config.retry_on_timeout,
        retry_on_http_5xx=config.retry_on_http_5xx,
    )
