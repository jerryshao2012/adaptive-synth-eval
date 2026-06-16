from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from adaptive_synth_eval.config.env import load_project_env, resolve_env_placeholders


class LoopProfileError(ValueError):
    """Raised when a loop profile is invalid or missing."""


@dataclass(frozen=True)
class LoopTarget:
    contract: str
    persona: str | None = None
    scenario: str | None = None
    adversarial_scenario: str | None = None
    dry_run: bool | None = None


@dataclass(frozen=True)
class LoopLLMConfig:
    provider: str
    model_name: str
    endpoint_url: str | None = None
    max_tokens_per_call: int = 1500
    temperature: float = 0.3
    fallback_provider: str | None = None


@dataclass(frozen=True)
class LoopProfile:
    profile_id: str
    readiness_level: str
    cadence: str
    targets: list[LoopTarget]
    source_path: Path
    max_iterations_per_cycle: int = 1
    budget_policy_ref: str | None = None
    escalation_rules: list[Any] = field(default_factory=list)
    human_gates: list[str] = field(default_factory=list)
    denylist: list[str] = field(default_factory=list)
    checker_policy: dict[str, Any] = field(default_factory=dict)
    llm_config: LoopLLMConfig | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "readiness_level": self.readiness_level,
            "cadence": self.cadence,
            "targets": [target.__dict__ for target in self.targets],
            "source_path": str(self.source_path),
            "max_iterations_per_cycle": self.max_iterations_per_cycle,
            "budget_policy_ref": self.budget_policy_ref,
            "human_gates": list(self.human_gates),
            "denylist": list(self.denylist),
            "checker_policy": dict(self.checker_policy),
            "llm_config": None if self.llm_config is None else self.llm_config.__dict__,
        }


def load_loop_profile(profile_ref: str, *, profiles_dir: str | Path = "loops/profiles") -> LoopProfile:
    profile_path = _resolve_profile_path(profile_ref, Path(profiles_dir))
    if not profile_path.exists():
        raise LoopProfileError(f"Loop profile not found: {profile_ref}")

    load_project_env(anchor=profile_path, override=False)
    payload = _load_payload(profile_path)
    if not isinstance(payload, dict):
        raise LoopProfileError("Loop profile must be a JSON/YAML object/dictionary")
    return parse_loop_profile(payload, source_path=profile_path)


def parse_loop_profile(payload: dict[str, Any], *, source_path: Path) -> LoopProfile:
    required = ["profile_id", "readiness_level", "cadence", "targets"]
    for key in required:
        if key not in payload:
            raise LoopProfileError(f"Missing required loop profile field: {key}")

    profile_id = str(payload["profile_id"]).strip()
    readiness_level = str(payload["readiness_level"]).strip().upper()
    cadence = str(payload["cadence"]).strip()
    if not profile_id:
        raise LoopProfileError("Loop profile field profile_id cannot be empty")
    if readiness_level not in {"L1", "L2", "L3"}:
        raise LoopProfileError("readiness_level must be one of L1, L2, or L3")
    if not cadence:
        raise LoopProfileError("Loop profile field cadence cannot be empty")

    targets = _parse_targets(payload["targets"], source_path=source_path)
    max_iterations = int(payload.get("max_iterations_per_cycle", 1))
    if max_iterations < 1:
        raise LoopProfileError("max_iterations_per_cycle must be >= 1")

    llm_payload = payload.get("llm_config")
    llm_config = _parse_llm_config(llm_payload) if isinstance(llm_payload, dict) else None
    checker_policy = payload.get("checker_policy") or {}
    if not isinstance(checker_policy, dict):
        raise LoopProfileError("checker_policy must be a mapping/dictionary when provided")

    return LoopProfile(
        profile_id=profile_id,
        readiness_level=readiness_level,
        cadence=cadence,
        targets=targets,
        source_path=source_path.resolve(),
        max_iterations_per_cycle=max_iterations,
        budget_policy_ref=_optional_str(payload.get("budget_policy_ref")),
        escalation_rules=list(payload.get("escalation_rules") or []),
        human_gates=[str(item) for item in (payload.get("human_gates") or [])],
        denylist=[str(item) for item in (payload.get("denylist") or [])],
        checker_policy=checker_policy,
        llm_config=llm_config,
    )


def _load_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)
    return resolve_env_placeholders(payload)


def _resolve_profile_path(profile_ref: str, profiles_dir: Path) -> Path:
    explicit = Path(profile_ref)
    if explicit.exists():
        return explicit.resolve()

    if explicit.suffix:
        return (profiles_dir / explicit.name).resolve()

    for suffix in (".yaml", ".yml", ".json"):
        candidate = profiles_dir / f"{profile_ref}{suffix}"
        if candidate.exists():
            return candidate.resolve()
    return (profiles_dir / profile_ref).resolve()


def _parse_targets(payload: Any, *, source_path: Path) -> list[LoopTarget]:
    if not isinstance(payload, list) or not payload:
        raise LoopProfileError("targets must be a non-empty list")

    repo_root = _find_project_root(source_path.parent)
    targets: list[LoopTarget] = []
    for item in payload:
        if not isinstance(item, dict):
            raise LoopProfileError("Each target must be a mapping/dictionary")
        contract = _optional_str(item.get("contract"))
        if not contract:
            raise LoopProfileError("Each target must include a contract path")
        contract_path = (repo_root / contract).resolve() if not Path(contract).is_absolute() else Path(contract)
        if not contract_path.exists():
            raise LoopProfileError(f"Target contract not found: {contract}")
        targets.append(
            LoopTarget(
                contract=contract,
                persona=_optional_str(item.get("persona")),
                scenario=_optional_str(item.get("scenario")),
                adversarial_scenario=_optional_str(item.get("adversarial_scenario")),
                dry_run=item.get("dry_run"),
            )
        )
    return targets


def _parse_llm_config(payload: dict[str, Any]) -> LoopLLMConfig:
    provider = _required_non_empty(payload, "provider")
    model_name = _required_non_empty(payload, "model_name")
    max_tokens = int(payload.get("max_tokens_per_call", 1500))
    if max_tokens < 1:
        raise LoopProfileError("llm_config.max_tokens_per_call must be >= 1")
    temperature = float(payload.get("temperature", 0.3))
    if temperature < 0.0 or temperature > 1.0:
        raise LoopProfileError("llm_config.temperature must be between 0.0 and 1.0")
    return LoopLLMConfig(
        provider=provider,
        model_name=model_name,
        endpoint_url=_optional_str(payload.get("endpoint_url")),
        max_tokens_per_call=max_tokens,
        temperature=temperature,
        fallback_provider=_optional_str(payload.get("fallback_provider")),
    )


def _find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_non_empty(payload: dict[str, Any], key: str) -> str:
    value = _optional_str(payload.get(key))
    if not value:
        raise LoopProfileError(f"Missing required loop profile field: llm_config.{key}")
    return value
