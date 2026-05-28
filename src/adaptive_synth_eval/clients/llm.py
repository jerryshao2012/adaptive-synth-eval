from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import SecretStr

logger = logging.getLogger(__name__)

# Load environment variables from .env file if it exists
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)


@dataclass(frozen=True)
class LLMResult:
    content: str
    raw: dict[str, Any]
    error: str | None = None


class LLMClient:
    """Configurable LLM client for user simulation and optional local judging/generation hooks.

    Supports multiple model providers via environment variables:
    - Azure OpenAI (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_API_KEY)
    - Anthropic (ANTHROPIC_API_KEY, MODEL_NAME)
    - OpenAI (OPENAI_API_KEY, MODEL_NAME)
    - Ollama (OLLAMA_BASE_URL, MODEL_NAME)
    """

    def __init__(self, enabled: bool = False, model_provider: str | None = None):
        self.enabled = enabled
        self.model_provider = model_provider or self._detect_provider()
        self._model = None

    def _detect_provider(self) -> str | None:
        """Auto-detect available LLM provider from environment variables."""
        if os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_DEPLOYMENT"):
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
            logger.debug(f"Detected Azure OpenAI provider: endpoint={endpoint}, deployment={deployment}")
            return "azure_openai"
        elif os.getenv("ANTHROPIC_API_KEY"):
            logger.debug("Detected Anthropic provider")
            return "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            logger.debug("Detected OpenAI provider")
            return "openai"
        elif os.getenv("OLLAMA_BASE_URL"):
            logger.debug("Detected Ollama provider")
            return "ollama"
        logger.warning(
            "No LLM provider detected. Configure one of: AZURE_OPENAI_ENDPOINT/DEPLOYMENT, ANTHROPIC_API_KEY, OPENAI_API_KEY, or OLLAMA_BASE_URL")
        return None

    def _get_model(self):
        """Lazy-initialize the chat model based on configured provider."""
        if self._model is not None:
            return self._model

        if not self.enabled or not self.model_provider:
            return None

        try:
            if self.model_provider == "azure_openai":
                from langchain_openai import AzureChatOpenAI

                endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
                deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
                api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview").strip()
                verify_ssl = os.getenv("VERIFY_SSL", "true").lower() != "false"

                logger.info(
                    f"Initializing Azure OpenAI: endpoint={endpoint}, deployment={deployment}, api_version={api_version}")
                auth_kwargs = self._get_azure_auth_kwargs()

                self._model = AzureChatOpenAI(
                    azure_endpoint=endpoint,
                    azure_deployment=deployment,
                    api_version=api_version,
                    temperature=0.7,
                    http_client=httpx.Client(verify=verify_ssl),
                    **auth_kwargs,
                )
                logger.info("Azure OpenAI model initialized successfully")

            elif self.model_provider == "anthropic":
                from langchain_anthropic import ChatAnthropic

                self._model = ChatAnthropic(
                    model=os.getenv("MODEL_NAME", "claude-sonnet-4-5-20250929"),
                    temperature=0.7,
                    api_key=SecretStr(os.getenv("ANTHROPIC_API_KEY", "")),
                )

            elif self.model_provider == "openai":
                from langchain_openai import ChatOpenAI

                self._model = ChatOpenAI(
                    model=os.getenv("MODEL_NAME", "gpt-4o-mini"),
                    temperature=0.7,
                    api_key=SecretStr(os.getenv("OPENAI_API_KEY", "")),
                )

            elif self.model_provider == "ollama":
                from langchain_ollama import ChatOllama

                self._model = ChatOllama(
                    model=os.getenv("MODEL_NAME", "qwen3.6:35b-a3b"),
                    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                    temperature=0.7,
                    keep_alive="15m",
                    reasoning=False,
                )

            else:
                raise ValueError(f"Unsupported model provider: {self.model_provider}")

        except ImportError as e:
            raise ImportError(
                f"Required package for {self.model_provider} not installed. "
                f"Install with: pip install langchain-{self.model_provider.replace('_', '-')}"
            ) from e

        return self._model

    def _get_azure_auth_kwargs(self) -> dict:
        """Return authentication kwargs for Azure OpenAI."""
        if os.getenv("AZURE_AUTH_TYPE") == "managed_identity":
            from azure.identity import ManagedIdentityCredential, get_bearer_token_provider

            credential = ManagedIdentityCredential(
                client_id=os.getenv("AZURE_CLIENT_ID")
            )
            token_provider = get_bearer_token_provider(
                credential, os.getenv("AZURE_OPENAI_SCOPE", "https://cognitiveservices.azure.com/.default")
            )
            return {"azure_ad_token_provider": token_provider}
        else:
            return {"api_key": SecretStr(os.getenv("AZURE_OPENAI_API_KEY", ""))}

    def complete(self, prompt: str) -> LLMResult:
        """Generate a completion using the configured LLM provider."""
        if not self.enabled:
            return LLMResult(content="", raw={"mock": True, "prompt": prompt}, error="llm_disabled")

        if not self.model_provider:
            return LLMResult(
                content="",
                raw={"mock": True, "prompt": prompt},
                error="no_provider_configured"
            )

        try:
            model = self._get_model()
            if model is None:
                return LLMResult(
                    content="",
                    raw={"mock": True, "prompt": prompt},
                    error="model_initialization_failed"
                )

            # Use LangChain's invoke method
            response = model.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            return LLMResult(
                content=str(content),
                raw={
                    "provider": self.model_provider,
                    "model": getattr(model, 'model_name', getattr(model, 'deployment_name', 'unknown')),
                    "usage": getattr(response, 'usage_metadata', None),
                },
                error=None,
            )

        except Exception as e:
            error_msg = f"LLM error ({self.model_provider}): {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return LLMResult(
                content="",
                raw={"mock": True, "prompt": prompt, "provider": self.model_provider, "exception": type(e).__name__},
                error=error_msg,
            )
