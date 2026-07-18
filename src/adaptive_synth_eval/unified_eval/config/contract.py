"""Parse a unified-eval YAML contract into a UnifiedContract dataclass.

Reuses ASE parsers for Persona/Scenario/TargetChatbot/TimeWindow so the schema stays
in lockstep with the synth pipeline.
"""
from __future__ import annotations

import json
from dataclasses import fields
from datetime import date
from pathlib import Path
from typing import Any, cast

import yaml

from adaptive_synth_eval.config.contract import (
    ContractError,
    _parse_persona,
    _parse_scenario,
    _parse_target_chatbot,
    _require_keys,
)
from adaptive_synth_eval.config.env import load_project_env, resolve_env_placeholders
from adaptive_synth_eval.config.schemas import (
    Persona,
    Scenario,
    TimeWindow,
)
from adaptive_synth_eval.unified_eval.config.schemas import (
    AdversarialScenario,
    ComponentOverrides,
    ConversationTurns,
    EvalPlan,
    EvalPlanEntry,
    LLMSpec,
    OutputConfig,
    RunSettings,
    Schedule,
    ScoringConfig,
    Suite,
    TrajectoryConfig,
    UnifiedContract,
)

_REQUIRED_TOP = [
    "suite",
    "llm",
    "target",
    "time_window",
    "persona_pool",
    "scenario_catalog",
    "eval_plan",
]


def load_unified_contract(path: str | Path) -> UnifiedContract:
    path = Path(path)
    if not path.exists():
        raise ContractError(f"Contract file not found: {path}")
    load_project_env(anchor=path, override=False)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)
    payload = resolve_env_placeholders(payload)
    return parse_unified_contract(payload, base_path=path.parent)


def parse_unified_contract(payload: dict[str, Any], *, base_path: Path | None = None) -> UnifiedContract:
    warnings: list[str] = []
    schema_version = int(payload.get("schema_version", 1))
    if schema_version not in {1, 2}:
        raise ContractError(
            f"Unsupported unified contract schema_version {schema_version}; supported versions are 1 and 2."
        )
    for key in _REQUIRED_TOP:
        if key not in payload:
            raise ContractError(f"Missing required contract section: {key}")

    suite = Suite(**_filter_keys(payload["suite"], Suite))
    run = RunSettings(**_filter_keys(payload.get("run", {}), RunSettings))

    llm = _parse_llm_spec(payload["llm"], warnings=warnings, context="llm")
    components = _parse_components(payload.get("components", {}), warnings)

    target_payload = payload["target"]
    target = _parse_target_chatbot(target_payload)
    # Optional LLM-as-target config (only used when target.mode == "llm").
    target_llm = (
        _parse_llm_spec(
            target_payload["chatbot_llm"], warnings=warnings, context="target.chatbot_llm"
        )
        if isinstance(target_payload.get("chatbot_llm"), dict)
        else None
    )
    target_system_prompt = str(target_payload.get("system_prompt", "") or "")

    window_payload = payload["time_window"]
    window = TimeWindow(
        start_day=date.fromisoformat(str(window_payload["start_day"])),
        num_synthetic_days=int(window_payload["num_synthetic_days"]),
        compressed_runtime_minutes=int(window_payload["compressed_runtime_minutes"]),
    )

    personas = [_parse_persona(_apply_persona_aliases(item, warnings)) for item in payload["persona_pool"]]
    scenarios = [_parse_scenario(item, warnings) for item in payload["scenario_catalog"]]

    scoring = _parse_scoring(payload.get("scoring", {}))

    # Extract adversarial scenarios defined directly in scenario_catalog
    adv_scenarios = []
    for item in payload.get("scenario_catalog", []):
        if "scenario_type" in item and "scenario_text" in item:
            adv_scenarios.append(
                _parse_adversarial(item, scoring.adversarial_failure_threshold, warnings)
            )

    # Also parse from adversarial_scenario_catalog if present
    if "adversarial_scenario_catalog" in payload:
        for item in payload["adversarial_scenario_catalog"]:
            # Avoid duplicate scenario IDs
            if not any(a.scenario_id == item["scenario_id"] for a in adv_scenarios):
                adv_scenarios.append(
                    _parse_adversarial(item, scoring.adversarial_failure_threshold, warnings)
                )

    eval_plan = _parse_eval_plan(payload["eval_plan"], warnings)
    trajectory = TrajectoryConfig(
        **_filter_keys(payload.get("trajectory", {}) or {}, TrajectoryConfig)
    )

    _validate_references(personas, scenarios, adv_scenarios, eval_plan)
    _validate_turns(eval_plan.conversation_turns)

    output_payload = payload.get("output", {})
    base_dir = Path(output_payload.get("base_dir", "outputs"))
    if base_path and not base_dir.is_absolute():
        base_dir = (base_path / base_dir).resolve()
    output = OutputConfig(base_dir=base_dir, run_id=output_payload.get("run_id"))

    if target.mode == "llm" and target_llm is None:
        raise ContractError(
            "target.mode == 'llm' requires target.chatbot_llm config with provider/model."
        )

    return UnifiedContract(
        suite=suite,
        run=run,
        llm=llm,
        components=components,
        target=target,
        time_window=window,
        persona_pool=personas,
        scenario_catalog=scenarios,
        adversarial_scenario_catalog=adv_scenarios,
        eval_plan=eval_plan,
        scoring=scoring,
        output=output,
        target_llm=target_llm,
        target_system_prompt=target_system_prompt,
        trajectory=trajectory,
        warnings=warnings,
    )


# --- Persona field aliases ----------------------------------------------------
# Unified contracts may use the domain-neutral names below in place of the
# original HR-bot-flavored names. ASE's Persona dataclass still uses the legacy
# names internally, so we map new -> old before delegating to ASE's parser.

_PERSONA_ALIASES = {
    "domain_familiarity": "hr_familiarity",
    "data_sensitivity": "privacy_sensitivity",
}


def _apply_persona_aliases(payload: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    out = dict(payload)
    persona_id = out.get("persona_id", "?")
    for new_name, legacy_name in _PERSONA_ALIASES.items():
        has_new = new_name in out
        has_legacy = legacy_name in out
        if has_new and has_legacy:
            raise ContractError(
                f"persona {persona_id!r} sets both {new_name!r} and legacy {legacy_name!r}; "
                "use only one (prefer the new name)."
            )
        if has_new:
            out[legacy_name] = out.pop(new_name)
        elif has_legacy:
            warnings.append(
                f"persona {persona_id!r} uses legacy field {legacy_name!r}; "
                f"prefer the domain-neutral {new_name!r}."
            )
    return out


def contract_to_dict(contract: UnifiedContract) -> dict[str, Any]:
    target = _target_to_dict(contract.target)
    if contract.target_llm is not None:
        target["chatbot_llm"] = _llm_to_dict(contract.target_llm)
    if contract.target_system_prompt:
        target["system_prompt"] = contract.target_system_prompt
    return {
        "schema_version": 2,
        "suite": contract.suite.__dict__,
        "run": contract.run.__dict__,
        "llm": _llm_to_dict(contract.llm),
        "components": {
            name: (_llm_to_dict(override) if override else None)
            for name, override in contract.components.__dict__.items()
        },
        "target": target,
        "time_window": {
            "start_day": contract.time_window.start_day.isoformat(),
            "num_synthetic_days": contract.time_window.num_synthetic_days,
            "compressed_runtime_minutes": contract.time_window.compressed_runtime_minutes,
        },
        "persona_pool": [_persona_to_dict(p) for p in contract.persona_pool],
        "scenario_catalog": [_scenario_to_dict(s) for s in contract.scenario_catalog],
        "adversarial_scenario_catalog": [a.__dict__ for a in contract.adversarial_scenario_catalog],
        "eval_plan": {
            "total_conversations": contract.eval_plan.total_conversations,
            "conversation_turns": contract.eval_plan.conversation_turns.__dict__,
            "attack_memory": contract.eval_plan.attack_memory,
            "seed_attack_memory_path": contract.eval_plan.seed_attack_memory_path,
            "attack_memory_max_entries": contract.eval_plan.attack_memory_max_entries,
            "entries": [
                {
                    "persona_id": entry.persona_id,
                    "synth_scenario_id": entry.synth_scenario_id,
                    "adversarial_scenario_id": entry.adversarial_scenario_id,
                    "weight": entry.weight,
                    "schedule": entry.schedule.__dict__,
                    "max_turns": entry.max_turns,
                }
                for entry in contract.eval_plan.entries
            ],
        },
        "scoring": {
            "synth": {"weights": contract.scoring.synth_weights},
            "adversarial": {"failure_threshold": contract.scoring.adversarial_failure_threshold},
        },
        "trajectory": contract.trajectory.__dict__,
        "output": {"base_dir": str(contract.output.base_dir), "run_id": contract.output.run_id},
    }


def _filter_keys(payload: dict[str, Any], cls) -> dict[str, Any]:
    names = {f.name for f in fields(cls)}
    return {k: payload[k] for k in names if k in payload}


def _provider_value(
        payload: dict[str, Any],
        nested: dict[str, Any],
        *,
        legacy_key: str,
        nested_key: str,
        warnings: list[str],
        context: str,
) -> Any:
    legacy = payload.get(legacy_key)
    value = nested.get(nested_key)
    if value is not None and legacy is not None and value != legacy:
        warnings.append(
            f"{context} sets both {legacy_key!r} and its nested equivalent; using the nested value."
        )
    return value if value is not None else legacy


def _parse_llm_spec(
        payload: dict[str, Any], *, warnings: list[str] | None = None, context: str = "llm"
) -> LLMSpec:
    warnings = warnings if warnings is not None else []
    azure = payload.get("azure", {}) or {}
    bedrock = payload.get("bedrock", {}) or {}
    ollama = payload.get("ollama", {}) or {}
    return LLMSpec(
        provider=str(payload.get("provider", "mock")),
        model=str(payload.get("model", "")),
        max_tokens=int(payload.get("max_tokens", 1024)),
        temperature=float(payload.get("temperature", 0.7)),
        api_key_env=payload.get("api_key_env"),
        azure_endpoint=_provider_value(
            payload, azure, legacy_key="azure_endpoint", nested_key="endpoint",
            warnings=warnings, context=context,
        ),
        azure_deployment=_provider_value(
            payload, azure, legacy_key="azure_deployment", nested_key="deployment",
            warnings=warnings, context=context,
        ),
        azure_api_version=_provider_value(
            payload, azure, legacy_key="azure_api_version", nested_key="api_version",
            warnings=warnings, context=context,
        ),
        bedrock_region=_provider_value(
            payload, bedrock, legacy_key="bedrock_region", nested_key="region",
            warnings=warnings, context=context,
        ),
        bedrock_endpoint=_provider_value(
            payload, bedrock, legacy_key="bedrock_endpoint", nested_key="endpoint",
            warnings=warnings, context=context,
        ),
        ollama_base_url=_provider_value(
            payload, ollama, legacy_key="ollama_base_url", nested_key="base_url",
            warnings=warnings, context=context,
        ),
    )


def _parse_components(payload: dict[str, Any], warnings: list[str]) -> ComponentOverrides:
    def _opt(key: str) -> LLMSpec | None:
        raw = payload.get(key)
        return (
            _parse_llm_spec(raw, warnings=warnings, context=f"components.{key}")
            if isinstance(raw, dict)
            else None
        )

    return ComponentOverrides(
        planner=_opt("planner"),
        generator=_opt("generator"),
        judge=_opt("judge"),
        policy=_opt("policy"),
        user_simulator=_opt("user_simulator"),
    )


def _parse_adversarial(
        payload: dict[str, Any], default_threshold: int, warnings: list[str]
) -> AdversarialScenario:
    _require_keys(payload, ["scenario_id", "scenario_type", "scenario_text"], "adversarial_scenario")
    judge_overrides = cast(dict[str, Any], payload.get("judge_overrides", {})) or {}
    if judge_overrides:
        warnings.append(
            f"adversarial scenario {payload['scenario_id']!r} defines judge_overrides; "
            "the values are preserved but are not currently applied."
        )
    return AdversarialScenario(
        scenario_id=str(payload["scenario_id"]),
        scenario_type=str(payload["scenario_type"]),
        scenario_text=str(payload["scenario_text"]),
        hijack_target=payload.get("hijack_target"),
        failure_threshold=int(payload.get("failure_threshold", default_threshold)),
        judge_overrides=judge_overrides,
        fresh_start_after_refusals=int(payload.get("fresh_start_after_refusals", 2)),
    )


def _parse_seed_attack_memory_path(raw: Any) -> str | list[str] | None:
    """Normalize the seed spec: a single path string, a list of paths, or None."""
    if not raw:
        return None
    if isinstance(raw, (list, tuple)):
        paths = [str(p) for p in raw if p]
        return paths or None
    return str(raw)


def _parse_eval_plan(payload: dict[str, Any], warnings: list[str]) -> EvalPlan:
    # `total_conversations` is now optional — when omitted, the run is budget-driven.
    _require_keys(payload, ["conversation_turns", "entries"], "eval_plan")
    turns_payload = payload["conversation_turns"]
    turns = ConversationTurns(min=int(turns_payload["min"]), max=int(turns_payload["max"]))
    entries = [_parse_entry(item, warnings) for item in payload["entries"]]
    raw_total = payload.get("total_conversations")
    total_conversations = int(raw_total) if raw_total is not None and isinstance(raw_total, (int, float, str)) else None
    attack_memory = str(payload.get("attack_memory", "shared"))
    if attack_memory not in {"shared", "per_persona", "none"}:
        raise ContractError(
            "eval_plan.attack_memory must be one of shared|per_persona|none"
        )
    return EvalPlan(
        total_conversations=total_conversations,
        conversation_turns=turns,
        entries=entries,
        attack_memory=attack_memory,
        seed_attack_memory_path=_parse_seed_attack_memory_path(
            payload.get("seed_attack_memory_path")
        ),
        attack_memory_max_entries=int(payload.get("attack_memory_max_entries", 50)),
    )


def _parse_entry(payload: dict[str, Any], warnings: list[str]) -> EvalPlanEntry:
    _require_keys(
        payload,
        ["persona_id", "synth_scenario_id", "adversarial_scenario_id"],
        "eval_plan.entry",
    )
    persona_id = str(payload["persona_id"])
    schedule_payload = payload.get("schedule")
    legacy_ratio = payload.get("synth_to_adversarial_ratio")

    if isinstance(schedule_payload, dict):
        schedule = _parse_schedule(schedule_payload)
    elif legacy_ratio is not None and isinstance(legacy_ratio, (int, float, str)):
        # Backwards-compat: old `synth_to_adversarial_ratio` becomes Bernoulli schedule.
        ratio = float(legacy_ratio)
        if not 0.0 <= ratio <= 1.0:
            raise ContractError(
                f"synth_to_adversarial_ratio must be in [0,1], got {ratio} for entry persona_id={persona_id!r}"
            )
        warnings.append(
            f"eval_plan.entries[persona_id={persona_id}] uses deprecated "
            "`synth_to_adversarial_ratio`; prefer `schedule: {mode: bernoulli, p_synth: <value>}`"
        )
        schedule = Schedule(mode="bernoulli", p_synth=ratio)
    else:
        schedule = Schedule()  # default: bernoulli with p_synth=0.3 (adversarial-leaning)

    return EvalPlanEntry(
        persona_id=persona_id,
        synth_scenario_id=str(payload["synth_scenario_id"]),
        adversarial_scenario_id=str(payload["adversarial_scenario_id"]),
        weight=float(payload.get("weight", 1.0)),
        schedule=schedule,
        max_turns=payload.get("max_turns"),
        synth_to_adversarial_ratio=(float(legacy_ratio) if legacy_ratio is not None else None),
    )


def _parse_schedule(payload: dict[str, Any]) -> Schedule:
    mode = str(payload.get("mode", "bernoulli"))
    if mode not in {"bernoulli", "phased", "min_each", "ramp"}:
        raise ContractError(
            f"schedule.mode must be one of bernoulli|phased|min_each|ramp, got {mode!r}"
        )
    p_synth = float(payload.get("p_synth", 0.3))
    if not 0.0 <= p_synth <= 1.0:
        raise ContractError(f"schedule.p_synth must be in [0,1], got {p_synth}")
    return Schedule(
        mode=mode,
        p_synth=p_synth,
        warmup_turns=int(payload.get("warmup_turns", 2)),
        min_synth=int(payload.get("min_synth", 0)),
        min_adversarial=int(payload.get("min_adversarial", 0)),
    )


def _parse_scoring(payload: dict[str, Any]) -> ScoringConfig:
    synth = payload.get("synth", {}) or {}
    adv = payload.get("adversarial", {}) or {}
    weights = synth.get("weights") or {
        "groundedness": 1.0, "relevance": 1.0, "safety": 1.0, "clarification": 1.0,
    }
    return ScoringConfig(
        synth_weights={k: float(v) for k, v in weights.items()},
        adversarial_failure_threshold=int(adv.get("failure_threshold", 3)),
    )


def _validate_references(
        personas: list[Persona],
        scenarios: list[Scenario],
        adv_scenarios: list[AdversarialScenario],
        eval_plan: EvalPlan,
) -> None:
    persona_ids = {p.persona_id for p in personas}
    scenario_ids = {s.scenario_id for s in scenarios}
    adv_ids = {a.scenario_id for a in adv_scenarios}
    for entry in eval_plan.entries:
        if entry.persona_id not in persona_ids:
            raise ContractError(f"Unknown persona_id in eval_plan: {entry.persona_id}")
        if entry.synth_scenario_id not in scenario_ids:
            raise ContractError(f"Unknown synth_scenario_id in eval_plan: {entry.synth_scenario_id}")
        if entry.adversarial_scenario_id not in adv_ids:
            raise ContractError(
                f"Unknown adversarial_scenario_id in eval_plan: {entry.adversarial_scenario_id}"
            )


def _validate_turns(turns: ConversationTurns) -> None:
    if turns.min < 1 or turns.max > 20 or turns.min > turns.max:
        raise ContractError("conversation_turns must be within 1-20 and min <= max")


def _llm_to_dict(spec: LLMSpec) -> dict[str, Any]:
    out: dict[str, Any] = {
        "provider": spec.provider,
        "model": spec.model,
        "max_tokens": spec.max_tokens,
        "temperature": spec.temperature,
    }
    if spec.api_key_env:
        out["api_key_env"] = spec.api_key_env
    azure = {
        "endpoint": spec.azure_endpoint,
        "deployment": spec.azure_deployment,
        "api_version": spec.azure_api_version,
    }
    bedrock = {"region": spec.bedrock_region, "endpoint": spec.bedrock_endpoint}
    ollama = {"base_url": spec.ollama_base_url}
    if any(value is not None for value in azure.values()):
        out["azure"] = {key: value for key, value in azure.items() if value is not None}
    if any(value is not None for value in bedrock.values()):
        out["bedrock"] = {key: value for key, value in bedrock.items() if value is not None}
    if any(value is not None for value in ollama.values()):
        out["ollama"] = {key: value for key, value in ollama.items() if value is not None}
    return out


def _persona_to_dict(persona: Persona) -> dict[str, Any]:
    out = {
        key: value
        for key, value in persona.__dict__.items()
        if key not in {"hr_familiarity", "privacy_sensitivity"} and value is not None
    }
    out["domain_familiarity"] = persona.domain_familiarity
    out["data_sensitivity"] = persona.data_sensitivity
    return out


def _scenario_to_dict(scenario: Scenario) -> dict[str, Any]:
    out = {
        key: value
        for key, value in scenario.__dict__.items()
        if key != "failure_injection" and value is not None
    }
    out["failure_injection"] = scenario.failure_injection.__dict__.copy()
    return out


def _target_to_dict(target) -> dict[str, Any]:
    out = target.__dict__.copy()
    if isinstance(out.get("auth"), dict):
        out["auth"] = {key: "<redacted>" for key in out["auth"]}
    if target.browser is not None:
        out["browser"] = target.browser.__dict__
    if target.agentcore is not None:
        out["agentcore"] = target.agentcore.__dict__
    return out
