from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from adaptive_synth_eval.config.schemas import (
    BurstPattern,
    ConversationTurns,
    FailureInjection,
    MixItem,
    OutputConfig,
    Persona,
    Scenario,
    SimulationContract,
    SimulationSuite,
    TargetChatbot,
    TimeWindow,
    TrafficOrchestration,
)


class ContractError(ValueError):
    """Raised when a simulation contract is invalid."""


def load_contract(path: str | Path) -> SimulationContract:
    path = Path(path)
    if not path.exists():
        raise ContractError(f"Contract file not found: {path}")
    payload = _load_payload(path)
    return parse_contract(payload, base_path=path.parent)


def parse_contract(payload: dict[str, Any], *, base_path: Path | None = None) -> SimulationContract:
    warnings: list[str] = []
    required_top = [
        "simulation_suite",
        "target_chatbot",
        "time_window",
        "persona_pool",
        "scenario_catalog",
        "traffic_orchestration",
    ]
    for key in required_top:
        if key not in payload:
            raise ContractError(f"Missing required contract section: {key}")

    suite = SimulationSuite(**payload["simulation_suite"])
    chatbot = TargetChatbot(**payload.get("target_chatbot", {}))
    window_payload = payload["time_window"]
    window = TimeWindow(
        start_day=date.fromisoformat(str(window_payload["start_day"])),
        num_synthetic_days=int(window_payload["num_synthetic_days"]),
        compressed_runtime_minutes=int(window_payload["compressed_runtime_minutes"]),
    )
    personas = [_parse_persona(item) for item in payload["persona_pool"]]
    scenarios = [_parse_scenario(item, warnings) for item in payload["scenario_catalog"]]
    traffic = _parse_traffic(payload["traffic_orchestration"])
    _validate_references(personas, scenarios, traffic)
    _validate_turns(traffic.conversation_turns)
    output_payload = payload.get("output", {})
    base_dir = Path(output_payload.get("base_dir", "outputs"))
    if base_path and not base_dir.is_absolute():
        base_dir = (base_path / base_dir).resolve()
    output = OutputConfig(base_dir=base_dir, run_id=output_payload.get("run_id"))
    return SimulationContract(
        simulation_suite=suite,
        target_chatbot=chatbot,
        time_window=window,
        persona_pool=personas,
        scenario_catalog=scenarios,
        traffic=traffic,
        output=output,
        warnings=warnings,
    )


def contract_to_dict(contract: SimulationContract) -> dict[str, Any]:
    return {
        "simulation_suite": contract.simulation_suite.__dict__,
        "target_chatbot": contract.target_chatbot.__dict__,
        "time_window": {
            "start_day": contract.time_window.start_day.isoformat(),
            "num_synthetic_days": contract.time_window.num_synthetic_days,
            "compressed_runtime_minutes": contract.time_window.compressed_runtime_minutes,
        },
        "persona_pool": [persona.__dict__ for persona in contract.persona_pool],
        "scenario_catalog": [
            {
                **{k: v for k, v in scenario.__dict__.items() if k != "failure_injection"},
                "failure_injection": scenario.failure_injection.__dict__,
            }
            for scenario in contract.scenario_catalog
        ],
        "traffic_orchestration": {
            "total_conversations": contract.traffic.total_conversations,
            "conversation_turns": contract.traffic.conversation_turns.__dict__,
            "mix": [item.__dict__ for item in contract.traffic.mix],
            "burst_patterns": [item.__dict__ for item in contract.traffic.burst_patterns],
            "synthetic_day_distribution": contract.traffic.synthetic_day_distribution,
            "random_seed": contract.traffic.random_seed,
            "max_concurrency": contract.traffic.max_concurrency,
            "batch_size": contract.traffic.batch_size,
            "rate_limit_per_minute": contract.traffic.rate_limit_per_minute,
        },
        "output": {"base_dir": str(contract.output.base_dir), "run_id": contract.output.run_id},
        "warnings": contract.warnings,
    }


def _load_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _parse_persona(payload: dict[str, Any]) -> Persona:
    required = [
        "persona_id",
        "role",
        "location",
        "seniority",
        "communication_style",
        "hr_familiarity",
        "privacy_sensitivity",
    ]
    _require_keys(payload, required, "persona")
    fields = Persona.__dataclass_fields__.keys()
    return Persona(**{key: payload.get(key) for key in fields if key in payload})


def _parse_scenario(payload: dict[str, Any], warnings: list[str]) -> Scenario:
    required = [
        "scenario_id",
        "domain",
        "intent",
        "expected_retrieval_topics",
        "failure_injection",
        "success_criteria",
    ]
    _require_keys(payload, required, "scenario")
    if "tool_expectations" in payload:
        warnings.append(
            f"scenario {payload['scenario_id']} contains legacy tool_expectations; ignored because tool calls are out of scope"
        )
    return Scenario(
        scenario_id=str(payload["scenario_id"]),
        domain=str(payload["domain"]),
        intent=str(payload["intent"]),
        expected_retrieval_topics=list(payload["expected_retrieval_topics"]),
        failure_injection=FailureInjection.from_dict(payload.get("failure_injection")),
        success_criteria=dict(payload["success_criteria"]),
        context=payload.get("context"),
    )


def _parse_traffic(payload: dict[str, Any]) -> TrafficOrchestration:
    turns = payload["conversation_turns"]
    return TrafficOrchestration(
        total_conversations=int(payload["total_conversations"]),
        conversation_turns=ConversationTurns(min=int(turns["min"]), max=int(turns["max"])),
        mix=[MixItem(**item) for item in payload["mix"]],
        burst_patterns=[BurstPattern(**item) for item in payload.get("burst_patterns", [])],
        synthetic_day_distribution=dict(payload.get("synthetic_day_distribution", {})),
        random_seed=payload.get("random_seed"),
        max_concurrency=int(payload.get("max_concurrency", 5)),
        batch_size=int(payload.get("batch_size", 50)),
        rate_limit_per_minute=payload.get("rate_limit_per_minute"),
    )


def _validate_turns(turns: ConversationTurns) -> None:
    if turns.min < 3 or turns.max > 8 or turns.min > turns.max:
        raise ContractError("conversation_turns must be within 3-8 and min must be <= max")


def _validate_references(personas: list[Persona], scenarios: list[Scenario], traffic: TrafficOrchestration) -> None:
    persona_ids = {item.persona_id for item in personas}
    scenario_ids = {item.scenario_id for item in scenarios}
    for item in traffic.mix:
        if item.persona_id not in persona_ids:
            raise ContractError(f"Unknown persona_id in traffic mix: {item.persona_id}")
        if item.scenario_id not in scenario_ids:
            raise ContractError(f"Unknown scenario_id in traffic mix: {item.scenario_id}")


def _require_keys(payload: dict[str, Any], keys: list[str], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ContractError(f"Missing required {label} field(s): {', '.join(missing)}")
