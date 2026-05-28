from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


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
class TargetChatbot:
    enabled: bool = True
    endpoint: str | None = None
    mode: str = "api"
    auth: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    browser: BrowserChatbot | None = None


@dataclass(frozen=True)
class TimeWindow:
    start_day: date
    num_synthetic_days: int
    compressed_runtime_minutes: int


@dataclass(frozen=True)
class Persona:
    persona_id: str
    role: str
    location: str
    seniority: str
    communication_style: str
    hr_familiarity: str
    privacy_sensitivity: str
    frustration_baseline: float | None = None
    preferred_language: str | None = None
    typing_style: str | None = None
    availability_context: str | None = None
    managerial_responsibility: bool | None = None


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
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: float(payload.get(key, 0.0)) for key in allowed})

    def planned_modes(self) -> list[str]:
        return [key for key, value in self.__dict__.items() if float(value or 0.0) > 0.0]


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    domain: str
    intent: str
    expected_retrieval_topics: list[str]
    failure_injection: FailureInjection
    success_criteria: dict[str, Any]
    context: str | None = None


@dataclass(frozen=True)
class ConversationTurns:
    min: int
    max: int


@dataclass(frozen=True)
class MixItem:
    persona_id: str
    scenario_id: str
    weight: float


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
class SimulationContract:
    simulation_suite: SimulationSuite
    target_chatbot: TargetChatbot
    time_window: TimeWindow
    persona_pool: list[Persona]
    scenario_catalog: list[Scenario]
    traffic: TrafficOrchestration
    output: OutputConfig
    warnings: list[str] = field(default_factory=list)

    @property
    def synthetic_flag(self) -> bool:
        return self.simulation_suite.synthetic_flag

    def persona_by_id(self) -> dict[str, Persona]:
        return {persona.persona_id: persona for persona in self.persona_pool}

    def scenario_by_id(self) -> dict[str, Scenario]:
        return {scenario.scenario_id: scenario for scenario in self.scenario_catalog}
