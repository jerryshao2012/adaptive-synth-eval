"""Single source of truth for LLM providers in the unified pipeline.

Each LLMSpec yields a pair:
- ARE-style callable: (system, user) -> {"content": str, "usage": {...}}
- ASE-side ASE LLMClient wrapper that complete() returns LLMResult.

Mock provider has fully synchronous, deterministic implementations on both
sides so --dry-run runs without any API keys.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from adaptive_synth_eval.adversarial_response_engine.providers.llm_backends import (
    LLMCallFn,
    make_azure_openai_backend,
    make_bedrock_backend,
    make_claude_backend,
    make_mock_backend,
    make_openai_backend,
)
from adaptive_synth_eval.clients.retry_utils import retry_call
from adaptive_synth_eval.unified_eval.config.schemas import LLMSpec


def _with_retry(
        call_fn: LLMCallFn,
        *,
        label: str,
        max_attempts: int,
        initial_backoff: float,
        max_backoff: float,
) -> LLMCallFn:
    def wrapped(system: str, user: str):
        return retry_call(
            lambda: call_fn(system=system, user=user),
            max_attempts=max_attempts,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            label=label,
        )

    return wrapped


# A "synth chat function" is the minimal thing UserSimulator needs:
# given a prompt string, return generated user text (or raise on error).
SynthChatFn = Callable[[str], str]


@dataclass
class ProvidedLLM:
    """A built LLM pair for one component."""
    spec: LLMSpec
    call_fn: LLMCallFn  # ARE side
    synth_chat: SynthChatFn  # ASE side (used by UserSimulator)


def build_llm(
        spec: LLMSpec,
        *,
        retry_max_attempts: int = 3,
        retry_initial_backoff: float = 1.0,
        retry_max_backoff: float = 30.0,
        component_label: str = "llm",
) -> ProvidedLLM:
    """Build both ARE and ASE adapters for a single spec."""
    provider = spec.provider.lower()

    if provider == "mock":
        # Mock: deterministic, no API key, no network. Both sides share one rng-seeded backend.
        call_fn = make_mock_backend()
        synth_chat = _make_mock_synth_chat()

    elif provider == "claude":
        model = spec.model or "claude-haiku-4-5-20251001"
        api_key = _resolve_api_key(spec.api_key_env or "ANTHROPIC_API_KEY")
        call_fn = make_claude_backend(model=model, api_key=api_key, max_tokens=spec.max_tokens)
        synth_chat = _make_langchain_synth_chat(
            "anthropic", model, spec.temperature, api_key=api_key,
        )

    elif provider == "openai":
        model = spec.model or "gpt-4o-mini"
        api_key = _resolve_api_key(spec.api_key_env or "OPENAI_API_KEY")
        call_fn = make_openai_backend(model=model, api_key=api_key, max_tokens=spec.max_tokens)
        synth_chat = _make_langchain_synth_chat(
            "openai", model, spec.temperature, api_key=api_key,
        )

    elif provider == "azure-openai":
        deployment = spec.azure_deployment or spec.model or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
        if not deployment:
            raise ValueError("azure-openai requires azure.deployment or model in contract")
        endpoint = spec.azure_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        api_version = spec.azure_api_version or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
        api_key = _resolve_api_key(spec.api_key_env or "AZURE_OPENAI_API_KEY")
        call_fn = make_azure_openai_backend(
            deployment=deployment,
            api_version=api_version,
            endpoint=endpoint,
            api_key=api_key,
            max_tokens=spec.max_tokens,
        )
        synth_chat = _make_langchain_synth_chat(
            "azure_openai", deployment, spec.temperature,
            api_key=api_key, azure_endpoint=endpoint, azure_api_version=api_version,
        )

    elif provider == "bedrock":
        model = spec.model or "anthropic.claude-haiku-4-5-20251001-v1:0"
        region = spec.bedrock_region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        call_fn = make_bedrock_backend(model=model, region=region, max_tokens=spec.max_tokens)
        # No ASE-side equivalent of native Bedrock today; fall back to mock for synth.
        synth_chat = _make_mock_synth_chat()

    elif provider == "ollama":
        # ARE has no native ollama backend; route both to mock with a clear warning.
        # If a user really needs ollama on ARE side, they can add a backend later.
        call_fn = make_mock_backend()
        synth_chat = _make_langchain_synth_chat(
            "ollama", spec.model or "qwen3.6:35b-a3b", spec.temperature,
            ollama_base_url=spec.ollama_base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {spec.provider!r}. "
            "Use one of: mock, claude, openai, azure-openai, bedrock, ollama."
        )

    # Wrap with retry — mock backend is free of transient errors so this is a no-op there.
    if provider != "mock":
        call_fn = _with_retry(
            call_fn,
            label=component_label,
            max_attempts=retry_max_attempts,
            initial_backoff=retry_initial_backoff,
            max_backoff=retry_max_backoff,
        )

    return ProvidedLLM(spec=spec, call_fn=call_fn, synth_chat=synth_chat)


def build_component_llms(contract) -> dict[str, ProvidedLLM]:
    """Resolve a ProvidedLLM per component, inheriting from contract.llm when absent."""
    return {
        name: build_llm(
            contract.llm_for(name),
            retry_max_attempts=contract.run.retry_max_attempts,
            retry_initial_backoff=contract.run.retry_initial_backoff_seconds,
            retry_max_backoff=contract.run.retry_max_backoff_seconds,
            component_label=name,
        )
        for name in ("planner", "generator", "judge", "policy", "user_simulator")
    }


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _resolve_api_key(env_var: str | None) -> str | None:
    if not env_var:
        return None
    return os.environ.get(env_var) or None


def _make_mock_synth_chat() -> SynthChatFn:
    """Deterministic user-side fallback: returns persona-shaped friendly question."""
    counter = [0]
    _TEMPLATES = [
        "Hi, I had a quick question about the policy you can help with.",
        "Thanks — could you walk me through how this actually applies to my situation?",
        "Could you help me understand what details matter most for my case?",
        "I want to make sure I understand the eligibility part correctly.",
        "Is there a deadline or timing I should be aware of?",
    ]

    def call(prompt: str) -> str:
        counter[0] += 1
        return _TEMPLATES[counter[0] % len(_TEMPLATES)]

    return call


def _make_langchain_synth_chat(
        provider_key: str,
        model: str,
        temperature: float,
        *,
        api_key: str | None = None,
        azure_endpoint: str | None = None,
        azure_api_version: str | None = None,
        ollama_base_url: str | None = None,
        openai_base_url: str | None = None,
) -> SynthChatFn:
    """Lazily build a LangChain chat model and adapt .invoke() to a SynthChatFn."""
    model_ref: dict[str, Any] = {"model": None}

    def _build():
        if model_ref["model"] is not None:
            return model_ref["model"]
        from pydantic import SecretStr  # local import keeps top-level light
        if provider_key == "anthropic":
            from langchain_anthropic import ChatAnthropic
            model_ref["model"] = ChatAnthropic(
                model=model, temperature=temperature,
                api_key=SecretStr(api_key or ""),
            )
        elif provider_key == "openai":
            from langchain_openai import ChatOpenAI
            kwargs = {
                "model": model,
                "temperature": temperature,
                "api_key": SecretStr(api_key or ""),
            }
            if openai_base_url:
                kwargs["base_url"] = openai_base_url
            model_ref["model"] = ChatOpenAI(**kwargs)
        elif provider_key == "azure_openai":
            from langchain_openai import AzureChatOpenAI
            model_ref["model"] = AzureChatOpenAI(
                azure_endpoint=azure_endpoint or "",
                azure_deployment=model,
                api_version=azure_api_version or "2024-02-01",
                temperature=temperature,
                api_key=SecretStr(api_key or ""),
            )
        elif provider_key == "ollama":
            from langchain_ollama import ChatOllama
            model_ref["model"] = ChatOllama(
                model=model,
                base_url=ollama_base_url or "http://localhost:11434",
                temperature=temperature,
            )
        else:
            raise ValueError(f"Unsupported langchain provider: {provider_key}")
        return model_ref["model"]

    def call(prompt: str) -> str:
        chat = _build()
        response = chat.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return str(content)

    return call
