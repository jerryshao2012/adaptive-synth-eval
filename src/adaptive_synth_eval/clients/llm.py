from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping

import httpx
from adaptive_synth_eval.clients.retry_utils import wrap_model_with_rate_limiting
from pydantic import SecretStr

logger = logging.getLogger(__name__)


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

    def __init__(
            self,
            enabled: bool = False,
            model_provider: str | None = None,
            config: Mapping[str, Any] | None = None,
    ):
        self.enabled = enabled
        self.config = dict(config or {})
        self.model_provider = self._normalize_provider(
            model_provider
            or self._provider_from_config()
            or self._detect_provider()
        )
        self._model = None

    def _provider_from_config(self) -> str | None:
        provider = self.config.get("provider")
        if provider is None:
            return None
        text = str(provider).strip()
        return text or None

    @staticmethod
    def _normalize_provider(provider: str | None) -> str | None:
        if provider is None:
            return None
        normalized = provider.strip().lower().replace("-", "_")
        aliases = {
            "azure": "azure_openai",
            "azureopenai": "azure_openai",
            "azure_openai": "azure_openai",
            "anthropic": "anthropic",
            "openai": "openai",
            "ollama": "ollama",
            "bedrock": "bedrock",
        }
        return aliases.get(normalized, normalized)

    def _cfg(self, key: str, env_var: str, default: str = "") -> str:
        value = self.config.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
        return os.getenv(env_var, default).strip()

    def _cfg_float(self, key: str, env_var: str, default: float) -> float:
        value = self.config.get(key)
        if value is not None and str(value).strip() != "":
            try:
                return float(value)
            except (TypeError, ValueError):
                logger.warning("Invalid float for config '%s': %r; using default=%s", key, value, default)
                return default
        raw = os.getenv(env_var)
        if raw is None or raw.strip() == "":
            return default
        try:
            return float(raw)
        except ValueError:
            logger.warning("Invalid float in env '%s': %r; using default=%s", env_var, raw, default)
            return default

    def _cfg_int(self, key: str, env_var: str, default: int) -> int:
        value = self.config.get(key)
        if value is not None and str(value).strip() != "":
            try:
                return int(value)
            except (TypeError, ValueError):
                logger.warning("Invalid int for config '%s': %r; using default=%s", key, value, default)
                return default
        raw = os.getenv(env_var)
        if raw is None or raw.strip() == "":
            return default
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid int in env '%s': %r; using default=%s", env_var, raw, default)
            return default

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
        elif os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_API_BASE"):
            logger.debug("Detected Ollama provider")
            return "ollama"
        elif os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
            logger.debug("Detected AWS Bedrock provider")
            return "bedrock"
        logger.warning(
            "No LLM provider detected. Configure one of: AZURE_OPENAI_ENDPOINT/DEPLOYMENT, ANTHROPIC_API_KEY, OPENAI_API_KEY, OLLAMA_BASE_URL/OLLAMA_API_BASE")
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

                endpoint = self._cfg("azure_endpoint", "AZURE_OPENAI_ENDPOINT")
                deployment = self._cfg("azure_deployment", "AZURE_OPENAI_DEPLOYMENT")
                api_version = self._cfg("azure_api_version", "AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
                verify_ssl = os.getenv("VERIFY_SSL", "true").lower() != "false"
                temperature = self._cfg_float("temperature", "MODEL_TEMPERATURE", 0.7)
                top_p = self._cfg_float("top_p", "MODEL_TOP_P", 1.0)
                max_tokens = self._cfg_int("max_tokens", "MODEL_MAX_TOKENS", 1024)

                logger.info(
                    f"Initializing Azure OpenAI: endpoint={endpoint}, deployment={deployment}, api_version={api_version}")
                auth_kwargs = self._get_azure_auth_kwargs()

                self._model = AzureChatOpenAI(
                    azure_endpoint=endpoint,
                    azure_deployment=deployment,
                    api_version=api_version,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    http_client=httpx.Client(verify=verify_ssl),
                    **auth_kwargs,
                )
                logger.info("Azure OpenAI model initialized successfully")

            elif self.model_provider == "anthropic":
                from langchain_anthropic import ChatAnthropic
                temperature = self._cfg_float("temperature", "MODEL_TEMPERATURE", 0.7)
                top_p = self._cfg_float("top_p", "MODEL_TOP_P", 1.0)
                max_tokens = self._cfg_int("max_tokens", "MODEL_MAX_TOKENS", 1024)
                model_name = self._cfg("model", "MODEL_NAME", "claude-sonnet-4-5-20250929")
                key_env = self._cfg("api_key_env", "ANTHROPIC_API_KEY_ENV", "ANTHROPIC_API_KEY")

                self._model = ChatAnthropic(
                    model=model_name,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    api_key=SecretStr(os.getenv(key_env, "")),
                )

            elif self.model_provider == "openai":
                from langchain_openai import ChatOpenAI
                temperature = self._cfg_float("temperature", "MODEL_TEMPERATURE", 0.7)
                top_p = self._cfg_float("top_p", "MODEL_TOP_P", 1.0)
                max_tokens = self._cfg_int("max_tokens", "MODEL_MAX_TOKENS", 1024)
                model_name = self._cfg("model", "MODEL_NAME", "gpt-4o-mini")
                key_env = self._cfg("api_key_env", "OPENAI_API_KEY_ENV", "OPENAI_API_KEY")

                self._model = ChatOpenAI(
                    model=model_name,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    api_key=SecretStr(os.getenv(key_env, "")),
                )

            elif self.model_provider == "ollama":
                from langchain_ollama import ChatOllama
                temperature = self._cfg_float("temperature", "MODEL_TEMPERATURE", 0.7)
                top_p = self._cfg_float("top_p", "MODEL_TOP_P", 1.0)
                model_name = self._cfg("model", "MODEL_NAME", "qwen3.6:35b-a3b")
                base_url = self._cfg("ollama_base_url", "OLLAMA_BASE_URL",
                                     os.getenv("OLLAMA_API_BASE", "http://localhost:11434"))

                self._model = ChatOllama(
                    model=model_name,
                    base_url=base_url,
                    temperature=temperature,
                    top_p=top_p,
                    keep_alive="15m",
                    reasoning=False,
                )

            elif self.model_provider == "bedrock":
                from langchain_openai import ChatOpenAI
                model_name = self._cfg("model", "MODEL_NAME", "amazon.nova-micro-v1:0")
                temperature = self._cfg_float("temperature", "MODEL_TEMPERATURE", 0.7)
                top_p = self._cfg_float("top_p", "MODEL_TOP_P", 1.0)
                max_tokens = self._cfg_int("max_tokens", "MODEL_MAX_TOKENS", 1024)
                key_env = self._cfg("api_key_env", "AWS_BEDROCK_TOKEN_ENV", "AWS_BEARER_TOKEN_BEDROCK")
                region = self._cfg("bedrock_region", "AWS_REGION", "us-east-1")
                default_base_url = f"https://bedrock-mantle.{region}.api.aws/v1"
                base_url = self._cfg("bedrock_endpoint", "AWS_BEDROCK_ENDPOINT", default_base_url)

                self._model = ChatOpenAI(
                    model=model_name,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    api_key=SecretStr(os.getenv(key_env, "")),
                    base_url=base_url,
                )

            else:
                raise ValueError(f"Unsupported model provider: {self.model_provider}")

            # Add retry and optional proactive shaping to simulator LLM requests.
            self._model = wrap_model_with_rate_limiting(self._model)

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
            key_env = self._cfg("api_key_env", "AZURE_OPENAI_API_KEY_ENV", "AZURE_OPENAI_API_KEY")
            return {"api_key": SecretStr(os.getenv(key_env, ""))}

    def complete(
            self,
            prompt: str,
            *,
            system_prompt: str | None = None,
            json_mode: bool = False,
    ) -> LLMResult:
        """Generate a completion, optionally using role-separated JSON judging."""
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

            invocation_model = model
            if json_mode and self.model_provider in {"openai", "azure_openai", "bedrock"}:
                invocation_model = model.bind(response_format={"type": "json_object"})

            invocation: Any = prompt
            if system_prompt is not None:
                from langchain_core.messages import HumanMessage, SystemMessage

                invocation = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=prompt),
                ]

            response = invocation_model.invoke(invocation)
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
            if self._is_content_filter_error(e):
                error_msg = f"LLM blocked by content filter ({self.model_provider}): {type(e).__name__}"
                logger.warning(error_msg)
                return LLMResult(
                    content="",
                    raw={
                        "mock": True,
                        "prompt": prompt,
                        "provider": self.model_provider,
                        "exception": type(e).__name__,
                        "error_code": "content_filter",
                    },
                    error="content_filter_blocked",
                )

            error_msg = f"LLM error ({self.model_provider}): {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return LLMResult(
                content="",
                raw={"mock": True, "prompt": prompt, "provider": self.model_provider, "exception": type(e).__name__},
                error=error_msg,
            )

    @staticmethod
    def _is_content_filter_error(error: Exception) -> bool:
        text = str(error).lower()
        markers = [
            "content_filter",
            "content filter",
            "responsibleaipolicyviolation",
            "response was filtered",
        ]
        return any(marker in text for marker in markers)
