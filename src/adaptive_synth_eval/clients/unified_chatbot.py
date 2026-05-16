"""
Unified chatbot client architecture supporting multiple RAG types and chatbot implementations.

Architecture Overview:
- BaseChatbotClient: Abstract base class defining the common interface
- Strategy classes: Implement specific chatbot protocols (VanillaRAG, GraphRAG, etc.)
- ChatbotClientFactory: Creates appropriate client based on configuration
- UnifiedChatbotClient: High-level facade that delegates to strategy instances

This design follows:
1. Open/Closed Principle: Easy to add new chatbot types
2. Single Responsibility: Each strategy handles one protocol
3. Dependency Injection: Strategies are injected into the unified client
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import requests
from adaptive_synth_eval.clients.retry_utils import retry_on_rate_limit


class ChatbotType(str, Enum):
    """Supported chatbot types."""
    VANILLA_RAG = "vanilla_rag"
    GRAPH_RAG = "graph_rag"
    # Future types can be added here
    # AZURE_OPENAI = "azure_openai"
    # CUSTOM_API = "custom_api"


@dataclass(frozen=True)
class ChatbotResponse:
    """Standardized response from any chatbot."""
    raw: dict[str, Any]
    bot_response: str
    latency_ms: float | None
    status_code: int
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None and self.status_code == 200


@dataclass
class ChatbotConfig:
    """Configuration for a chatbot instance."""
    chatbot_type: ChatbotType
    endpoint: str
    timeout_seconds: float = 60.0
    auth: dict[str, Any] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "ChatbotConfig":
        """Create config from dictionary."""
        return cls(
            chatbot_type=ChatbotType(config.get("chatbot_type", "vanilla_rag")),
            endpoint=config["endpoint"],
            timeout_seconds=config.get("timeout_seconds", 60.0),
            auth=config.get("auth", {}),
            extra_params=config.get("extra_params", {}),
        )


class BaseChatbotStrategy(ABC):
    """
    Abstract strategy for chatbot communication.
    
    Each concrete strategy implements the protocol-specific logic for:
    - Building request payloads
    - Sending HTTP requests
    - Parsing responses
    - Extracting bot text
    """

    def __init__(self, config: ChatbotConfig):
        self.config = config

    @abstractmethod
    def build_payload(self, question: str, **kwargs) -> dict[str, Any]:
        """Build the request payload for this chatbot type."""
        pass

    @abstractmethod
    def extract_bot_response(self, raw_response: dict[str, Any]) -> str:
        """Extract the bot's text response from raw API response."""
        pass

    @abstractmethod
    def extract_metadata(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        """Extract additional metadata from the response."""
        pass

    def send_request(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float, int, Optional[str]]:
        """
        Send HTTP request and return (response_data, latency_ms, status_code, error).
        
        This is a common implementation that can be overridden if needed.
        """
        headers = {"Content-Type": "application/json"}

        # Add authentication if configured
        if self.config.auth.get("type") == "bearer" and self.config.auth.get("env_var"):
            import os
            token = os.getenv(str(self.config.auth["env_var"]))
            if token:
                headers["Authorization"] = f"Bearer {token}"

        start = time.perf_counter()
        try:
            response = requests.post(
                self.config.endpoint,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds
            )
            latency_ms = (time.perf_counter() - start) * 1000
            status_code = response.status_code

            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text}
                error = "Non-JSON response"

            return data, latency_ms, status_code, None

        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000 if 'start' in locals() else None
            return {}, latency_ms or 0.0, 0, str(e)

    def query(self, question: str, **kwargs) -> ChatbotResponse:
        """
        Main query method that orchestrates the full request-response cycle.
        """
        payload = self.build_payload(question, **kwargs)
        raw_response, latency_ms, status_code, error = self._send_request_with_retry(payload)

        if error:
            return ChatbotResponse(
                raw=raw_response,
                bot_response="",
                latency_ms=latency_ms,
                status_code=status_code,
                error=error
            )

        bot_response = self.extract_bot_response(raw_response)
        metadata = self.extract_metadata(raw_response)

        return ChatbotResponse(
            raw=raw_response,
            bot_response=bot_response,
            latency_ms=latency_ms,
            status_code=status_code,
            metadata=metadata
        )

    @retry_on_rate_limit(max_retries=3, initial_backoff=1.0, max_backoff=30.0)
    def _send_request_with_retry(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float, int, Optional[str]]:
        """
        Send HTTP request with retry logic and return (response_data, latency_ms, status_code, error).
        
        This wraps the send_request method with rate limit retry logic.
        """
        return self.send_request(payload)


class VanillaRAGStrategy(BaseChatbotStrategy):
    """
    Strategy for Vanilla RAG endpoint.
    
    Request format:
    {
        "query": "...",
        "bmo_content": [...],
        "butler_11m_config": {
            "rag_model": [...],
            "rag_temperature": 0.01,
            "source_document_reference": "true"
        }
    }
    
    Response format:
    {
        "llm_response": "...",
        "retrieved_content": {...},
        ...
    }
    """

    def build_payload(self, question: str, **kwargs) -> dict[str, Any]:
        bmo_content = kwargs.get("bmo_content", ["Policies and Procedures"])
        rag_model = kwargs.get("rag_model", ["Deployment-Model-gpt-4.1"])
        rag_temperature = kwargs.get("rag_temperature", 0.01)
        source_document_reference = kwargs.get("source_document_reference", "true")

        return {
            "query": question,
            "bmo_content": bmo_content,
            "butler_11m_config": {
                "rag_model": rag_model,
                "rag_temperature": rag_temperature,
                "source_document_reference": source_document_reference,
            },
        }

    def extract_bot_response(self, raw_response: dict[str, Any]) -> str:
        return str(raw_response.get("llm_response", "") or "").strip()

    def extract_metadata(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        return {
            "retrieved_content": raw_response.get("retrieved_content", {}),
            "used_bmo_content": raw_response.get("used_bmo_content", []),
        }


class GraphRAGStrategy(BaseChatbotStrategy):
    """
    Strategy for Graph RAG endpoint.
    
    Request format:
    {
        "query": "...",
        "bmo_content": [...],
        "session_id": "...",
        "user_id": "..."
    }
    
    Response format:
    {
        "llm_response": "...",
        "graph": "...",
        "retrieved_content": "...",
        "used_bmo_content": [...],
        "references": "...",
        "error": "..."
    }
    """

    def build_payload(self, question: str, **kwargs) -> dict[str, Any]:
        import uuid

        bmo_content = kwargs.get("bmo_content", ["BMO Policy & Procedure"])
        session_id = kwargs.get("session_id", str(uuid.uuid4()))
        user_id = kwargs.get("user_id", f"user_{str(uuid.uuid4())[:8]}")

        return {
            "query": question,
            "bmo_content": bmo_content,
            "session_id": session_id,
            "user_id": user_id,
        }

    def extract_bot_response(self, raw_response: dict[str, Any]) -> str:
        return str(raw_response.get("llm_response", "") or "").strip()

    def extract_metadata(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        return {
            "graph": raw_response.get("graph", ""),
            "retrieved_content": raw_response.get("retrieved_content", ""),
            "used_bmo_content": raw_response.get("used_bmo_content", []),
            "references": raw_response.get("references", ""),
        }


class ChatbotClientFactory:
    """
    Factory that creates the appropriate chatbot strategy based on configuration.
    """

    _strategies: dict[ChatbotType, type[BaseChatbotStrategy]] = {
        ChatbotType.VANILLA_RAG: VanillaRAGStrategy,
        ChatbotType.GRAPH_RAG: GraphRAGStrategy,
    }

    @classmethod
    def register_strategy(cls, chatbot_type: ChatbotType, strategy_class: type[BaseChatbotStrategy]):
        """Register a new strategy type (for extensibility)."""
        cls._strategies[chatbot_type] = strategy_class

    @classmethod
    def create(cls, config: ChatbotConfig) -> BaseChatbotStrategy:
        """Create a chatbot strategy instance based on config."""
        strategy_class = cls._strategies.get(config.chatbot_type)
        if not strategy_class:
            raise ValueError(f"Unsupported chatbot type: {config.chatbot_type}")
        return strategy_class(config)


class UnifiedChatbotClient:
    """
    High-level facade for interacting with any chatbot type.
    
    Usage:
        # Create config
        config = ChatbotConfig(
            chatbot_type=ChatbotType.VANILLA_RAG,
            endpoint="https://...",
            extra_params={"rag_model": ["gpt-4"]}
        )
        
        # Create client
        client = UnifiedChatbotClient(config)
        
        # Query
        response = client.query("What is parental leave?")
        print(response.bot_response)
    """

    def __init__(self, config: ChatbotConfig):
        self.config = config
        self.strategy = ChatbotClientFactory.create(config)

    def query(self, question: str, **kwargs) -> ChatbotResponse:
        """Send a query to the chatbot and return standardized response."""
        return self.strategy.query(question, **kwargs)

    @property
    def chatbot_type(self) -> ChatbotType:
        return self.config.chatbot_type

    @property
    def endpoint(self) -> str:
        return self.config.endpoint


# Convenience function for quick setup
def create_chatbot_client(
        chatbot_type: str,
        endpoint: str,
        **kwargs
) -> UnifiedChatbotClient:
    """
    Quick helper to create a chatbot client.
    
    Args:
        chatbot_type: One of "vanilla_rag", "graph_rag"
        endpoint: The API endpoint URL
        **kwargs: Additional config parameters (timeout_seconds, auth, extra_params)
    
    Returns:
        Configured UnifiedChatbotClient instance
    """
    config = ChatbotConfig(
        chatbot_type=ChatbotType(chatbot_type),
        endpoint=endpoint,
        **kwargs
    )
    return UnifiedChatbotClient(config)
