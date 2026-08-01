from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class SimulationSuite:
    suite_id: str
    target_application: str
    run_mode: str
    synthetic_flag: bool = True


@dataclass(frozen=True)
class BrowserChatbot:
    url: str
    input_selector: str
    submit_selector: str
    response_selector: str
    browser_type: str = "chromium"
    ready_selector: str | None = None
    response_timeout_seconds: float = 60.0
    headless: bool = False


@dataclass(frozen=True)
class AgentCoreTarget:
    region: str = "us-east-1"
    agent_runtime_arn: str | None = None
    qualifier: str | None = None
    payload_prompt_key: str = "prompt"
    runtime_session_id_prefix: str = "ase_"


@dataclass(frozen=True)
class TargetChatbot:
    enabled: bool = True
    endpoint: str | None = None
    mode: str = "api"
    auth: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    retry_max_retries: int = 2
    retry_initial_backoff_seconds: float = 1.0
    retry_max_backoff_seconds: float = 20.0
    retry_backoff_multiplier: float = 2.0
    retry_jitter: bool = True
    retry_on_timeout: bool = True
    retry_on_http_5xx: bool = False
    browser: BrowserChatbot | None = None
    agentcore: AgentCoreTarget | None = None
    # Optional LLM request parameters forwarded in the chatbot API payload.
    # When set here they take precedence over the CHATBOT_MODEL /
    # CHATBOT_TEMPERATURE / CHATBOT_SOURCE_DOCUMENT_REFERENCE env vars,
    # giving the contract YAML a single place to configure both the harness
    # LLM (llm: block) and the target chatbot's own LLM knobs (target: block).
    chatbot_model: list[str] | None = None
    chatbot_temperature: float | None = None
    source_doc_ref: str | None = None


@dataclass(frozen=True)
class TimeWindow:
    start_day: date
    num_synthetic_days: int
    compressed_runtime_minutes: int


@dataclass(frozen=True)
class TimeProfileWindow:
    period_id: str
    start_time: str
    end_time: str
    traffic_weight: float
    conversation_mode: str = "default"
    behavior_mode: str = "default"
    recipe_weights: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "recipe_weights", MappingProxyType(dict(self.recipe_weights))
        )


@dataclass(frozen=True)
class TimeProfile:
    windows: tuple[TimeProfileWindow, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "windows", tuple(self.windows))


@dataclass(frozen=True)
class Persona:
    persona_id: str
    role: str
    location: str
    seniority: str
    communication_style: str
    hr_familiarity: str
    privacy_sensitivity: str
    domain_familiarity: str | None = None
    data_sensitivity: str | None = None
    frustration_baseline: float | None = None
    preferred_language: str | None = None
    typing_style: str | None = None
    availability_context: str | None = None
    managerial_responsibility: bool | None = None

    def __post_init__(self) -> None:
        if self.domain_familiarity is None:
            object.__setattr__(self, "domain_familiarity", self.hr_familiarity)
        if self.data_sensitivity is None:
            object.__setattr__(self, "data_sensitivity", self.privacy_sensitivity)


@dataclass(frozen=True)
class FailureInjection:
    ambiguity: float = 0.0
    missing_information: float = 0.0
    typos: float = 0.0
    frustration: float = 0.0
    policy_boundary_pressure: float = 0.0
    contradictory_inputs: float = 0.0
    repeated_clarification_loop: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "FailureInjection":
        payload = payload or {}
        allowed = {f.name for f in dataclasses.fields(cls)}
        return cls(**{key: float(payload.get(key, 0.0)) for key in allowed})

    def planned_modes(self) -> list[str]:
        return [key for key, value in self.__dict__.items() if float(value or 0.0) > 0.0]


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    domain: str | None = None
    intent: str | None = None
    expected_retrieval_topics: list[str] = field(default_factory=list)
    failure_injection: FailureInjection = field(default_factory=FailureInjection)
    success_criteria: dict[str, Any] = field(default_factory=dict)
    context: str | None = None

    # Extended adversarial fields
    scenario_type: str | None = None
    scenario_text: str | None = None
    hijack_target: str | None = None
    failure_threshold: int | None = None
    judge_overrides: dict[str, Any] = field(default_factory=dict)
    fresh_start_after_refusals: int | None = None
    reference_answer: str | None = None


@dataclass(frozen=True)
class ConversationTurns:
    min: int
    max: int


@dataclass(frozen=True)
class MixItem:
    persona_id: str
    scenario_id: str
    weight: float
    recipe_id: str | None = None


@dataclass(frozen=True)
class BurstPattern:
    name: str
    synthetic_day: int
    traffic_multiplier: float
    scenario_filter: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TrafficOrchestration:
    total_conversations: int
    conversation_turns: ConversationTurns
    mix: list[MixItem]
    burst_patterns: list[BurstPattern] = field(default_factory=list)
    synthetic_day_distribution: dict[str, float] = field(default_factory=dict)
    random_seed: int | None = None
    max_concurrency: int = 5
    batch_size: int = 50
    rate_limit_per_minute: int | None = None


@dataclass(frozen=True)
class OutputConfig:
    base_dir: Path
    run_id: str | None = None


@dataclass(frozen=True)
class SimulatedLLMConfig:
    provider: str | None = None
    model: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.7
    api_key_env: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    azure_api_version: str | None = None
    bedrock_region: str | None = None
    bedrock_endpoint: str | None = None
    ollama_base_url: str | None = None


@dataclass(frozen=True)
class SimulationContract:
    simulation_suite: SimulationSuite
    target: TargetChatbot
    time_window: TimeWindow
    persona_pool: list[Persona]
    scenario_catalog: list[Scenario]
    traffic: TrafficOrchestration
    output: OutputConfig
    llm: SimulatedLLMConfig = field(default_factory=SimulatedLLMConfig)
    warnings: list[str] = field(default_factory=list)
    time_profile: TimeProfile | None = None

    @property
    def synthetic_flag(self) -> bool:
        return self.simulation_suite.synthetic_flag

    def persona_by_id(self) -> dict[str, Persona]:
        return {persona.persona_id: persona for persona in self.persona_pool}

    def scenario_by_id(self) -> dict[str, Scenario]:
        return {scenario.scenario_id: scenario for scenario in self.scenario_catalog}
