from __future__ import annotations

import json
from dataclasses import fields
from datetime import date
from pathlib import Path
from typing import Any, cast

import yaml
from adaptive_synth_eval.config.env import load_project_env, resolve_env_placeholders

from adaptive_synth_eval.config.schemas import (
    AgentCoreTarget,
    BrowserChatbot,
    BurstPattern,
    ConversationTurns,
    FailureInjection,
    MixItem,
    OutputConfig,
    Persona,
    Scenario,
    SimulatedLLMConfig,
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
    load_project_env(anchor=path, override=False)
    payload = _load_payload(path)
    return parse_contract(payload, base_path=path.parent)


def parse_contract(payload: dict[str, Any], *, base_path: Path | None = None) -> SimulationContract:
    warnings: list[str] = []
    required_top = [
        "simulation_suite",
        "target",
        "time_window",
        "persona_pool",
        "scenario_catalog",
        "traffic_orchestration",
    ]
    for key in required_top:
        if key not in payload:
            raise ContractError(f"Missing required contract section: {key}")

    suite = SimulationSuite(**payload["simulation_suite"])
    chatbot = _parse_target_chatbot(payload.get("target", {}))
    llm = _parse_simulated_llm(payload.get("llm", {}))
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
        target=chatbot,
        llm=llm,
        time_window=window,
        persona_pool=personas,
        scenario_catalog=scenarios,
        traffic=traffic,
        output=output,
        warnings=warnings,
    )


def contract_to_dict(contract: SimulationContract) -> dict[str, Any]:
    target_data = contract.target.__dict__.copy()
    if contract.target.browser is not None:
        target_data["browser"] = contract.target.browser.__dict__
    if contract.target.agentcore is not None:
        target_data["agentcore"] = contract.target.agentcore.__dict__
    return {
        "simulation_suite": contract.simulation_suite.__dict__,
        "target": target_data,
        "llm": {
            "provider": contract.llm.provider,
            "model": contract.llm.model,
            "max_tokens": contract.llm.max_tokens,
            "temperature": contract.llm.temperature,
            "api_key_env": contract.llm.api_key_env,
            "azure": {
                "endpoint": contract.llm.azure_endpoint,
                "deployment": contract.llm.azure_deployment,
                "api_version": contract.llm.azure_api_version,
            },
            "bedrock": {
                "region": contract.llm.bedrock_region,
                "endpoint": contract.llm.bedrock_endpoint,
            },
            "ollama": {
                "base_url": contract.llm.ollama_base_url,
            },
        },
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
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)

    # Resolve environment variables in the entire payload
    return resolve_env_placeholders(payload)


def _parse_persona(payload: dict[str, Any]) -> Persona:
    payload = dict(payload)
    if "domain_familiarity" in payload:
        payload["hr_familiarity"] = payload.get("domain_familiarity")
    if "data_sensitivity" in payload:
        payload["privacy_sensitivity"] = payload.get("data_sensitivity")

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
    field_names = {f.name for f in fields(Persona)}
    return Persona(**{key: payload.get(key) for key in field_names if key in payload})


def _parse_simulated_llm(payload: dict[str, Any]) -> SimulatedLLMConfig:
    if not isinstance(payload, dict):
        payload = {}
    azure = payload.get("azure") if isinstance(payload.get("azure"), dict) else {}
    bedrock = payload.get("bedrock") if isinstance(payload.get("bedrock"), dict) else {}
    ollama = payload.get("ollama") if isinstance(payload.get("ollama"), dict) else {}

    provider_raw = payload.get("provider")
    model_raw = payload.get("model")
    api_key_env_raw = payload.get("api_key_env")
    return SimulatedLLMConfig(
        provider=str(provider_raw).strip() if provider_raw is not None and str(provider_raw).strip() else None,
        model=str(model_raw).strip() if model_raw is not None and str(model_raw).strip() else None,
        max_tokens=int(payload.get("max_tokens", 1024)),
        temperature=float(payload.get("temperature", 0.7)),
        api_key_env=(
            str(api_key_env_raw).strip()
            if api_key_env_raw is not None and str(api_key_env_raw).strip()
            else None
        ),
        azure_endpoint=(
            str(azure.get("endpoint")).strip()
            if azure.get("endpoint") is not None and str(azure.get("endpoint")).strip()
            else None
        ),
        azure_deployment=(
            str(azure.get("deployment")).strip()
            if azure.get("deployment") is not None and str(azure.get("deployment")).strip()
            else None
        ),
        azure_api_version=(
            str(azure.get("api_version")).strip()
            if azure.get("api_version") is not None and str(azure.get("api_version")).strip()
            else None
        ),
        bedrock_region=(
            str(bedrock.get("region")).strip()
            if bedrock.get("region") is not None and str(bedrock.get("region")).strip()
            else None
        ),
        bedrock_endpoint=(
            str(bedrock.get("endpoint")).strip()
            if bedrock.get("endpoint") is not None and str(bedrock.get("endpoint")).strip()
            else None
        ),
        ollama_base_url=(
            str(ollama.get("base_url")).strip()
            if ollama.get("base_url") is not None and str(ollama.get("base_url")).strip()
            else None
        ),
    )


def _parse_target_chatbot(payload: dict[str, Any]) -> TargetChatbot:
    browser_payload = payload.get("browser")
    browser = BrowserChatbot(**browser_payload) if isinstance(browser_payload, dict) else None
    agentcore_payload = payload.get("agentcore")
    agentcore = AgentCoreTarget(**agentcore_payload) if isinstance(agentcore_payload, dict) else None
    skip = {"browser", "agentcore", "chatbot_model", "chatbot_temperature", "source_doc_ref"}
    field_names = {f.name for f in fields(TargetChatbot)} - skip
    values = {key: payload.get(key) for key in field_names if key in payload}

    # chatbot_model: YAML list or env-var-resolved comma-separated string.
    raw_model = payload.get("chatbot_model")
    if isinstance(raw_model, list):
        chatbot_model: list[str] | None = [str(m).strip() for m in raw_model if str(m).strip()]
    elif isinstance(raw_model, str) and raw_model.strip():
        chatbot_model = [m.strip() for m in raw_model.split(",") if m.strip()]
    else:
        chatbot_model = None

    # chatbot_temperature: YAML float or env-var-resolved string.
    raw_temp = payload.get("chatbot_temperature")
    if raw_temp is not None and str(raw_temp).strip():
        try:
            chatbot_temperature: float | None = float(raw_temp)
        except (ValueError, TypeError):
            chatbot_temperature = None
    else:
        chatbot_temperature = None

    # source_doc_ref: plain string (or resolved from env).
    raw_ref = payload.get("source_doc_ref")
    source_doc_ref: str | None = str(raw_ref).strip() if isinstance(raw_ref, str) and raw_ref.strip() else None

    return TargetChatbot(
        **values,
        browser=browser,
        agentcore=agentcore,
        chatbot_model=chatbot_model or None,
        chatbot_temperature=chatbot_temperature,
        source_doc_ref=source_doc_ref,
    )


def _parse_scenario(payload: dict[str, Any], warnings: list[str]) -> Scenario:
    is_adversarial = "scenario_type" in payload and "scenario_text" in payload
    if is_adversarial:
        payload = dict(payload)
        payload.setdefault("domain", None)
        payload.setdefault("intent", None)
        payload.setdefault("expected_retrieval_topics", [])
        payload.setdefault("failure_injection", {})
        payload.setdefault("success_criteria", {})

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
        domain=str(payload["domain"]) if payload.get("domain") is not None else None,
        intent=str(payload["intent"]) if payload.get("intent") is not None else None,
        expected_retrieval_topics=list(payload["expected_retrieval_topics"]),
        failure_injection=FailureInjection.from_dict(payload.get("failure_injection")),
        success_criteria=cast(dict[str, Any], payload["success_criteria"]) if isinstance(payload["success_criteria"],
                                                                                         dict) else {},
        context=payload.get("context"),
        reference_answer=payload.get("reference_answer"),
        scenario_type=str(payload["scenario_type"]) if payload.get("scenario_type") is not None else None,
        scenario_text=str(payload["scenario_text"]) if payload.get("scenario_text") is not None else None,
        hijack_target=str(payload["hijack_target"]) if payload.get("hijack_target") is not None else None,
        failure_threshold=int(payload["failure_threshold"]) if payload.get("failure_threshold") is not None else None,
        judge_overrides=cast(dict[str, Any], payload.get("judge_overrides")) or {},
        fresh_start_after_refusals=int(payload["fresh_start_after_refusals"]) if payload.get(
            "fresh_start_after_refusals") is not None else None,
    )


def _parse_traffic(payload: dict[str, Any]) -> TrafficOrchestration:
    turns = payload["conversation_turns"]
    return TrafficOrchestration(
        total_conversations=int(payload["total_conversations"]),
        conversation_turns=ConversationTurns(min=int(turns["min"]), max=int(turns["max"])),
        mix=[MixItem(**item) for item in payload["mix"]],
        burst_patterns=[BurstPattern(**item) for item in payload.get("burst_patterns", [])],
        synthetic_day_distribution=cast(dict[str, float], payload.get("synthetic_day_distribution", {})),
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
