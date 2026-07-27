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
class LearningTournamentConfig:
    initial_pairs: int = 20
    batch_pairs: int = 20
    max_pairs: int = 100


@dataclass(frozen=True)
class LearningPromotionConfig:
    novelty_weight: float = 0.7
    coverage_weight: float = 0.3
    max_detection_drop_points: float = 5.0
    max_judge_error_increase_points: float = 1.0
    max_token_cost_increase_ratio: float = 0.2


@dataclass(frozen=True)
class LearningConfig:
    enabled: bool = False
    evidence_source: str = "synthetic_only"
    min_new_runs: int = 3
    min_new_adversarial_conversations: int = 100
    candidate_kinds: tuple[str, ...] = ("policy", "persona", "scenario")
    validation_contracts: tuple[str, ...] = ()
    require_human_approval: bool = True
    tournament: LearningTournamentConfig = field(
        default_factory=LearningTournamentConfig
    )
    promotion: LearningPromotionConfig = field(default_factory=LearningPromotionConfig)


@dataclass(frozen=True)
class LoopProfile:
    profile_id: str
    readiness_level: str
    cadence: str
    targets: list[LoopTarget]
    source_path: Path
    paused: bool = False
    priority: int = 100
    active_windows: list[str] = field(default_factory=list)
    max_iterations_per_cycle: int = 1
    budget_policy_ref: str | None = None
    daily_run_cap: int | None = None
    daily_token_cap: int | None = None
    escalation_rules: list[Any] = field(default_factory=list)
    human_gates: list[str] = field(default_factory=list)
    denylist: list[str] = field(default_factory=list)
    checker_policy: dict[str, Any] = field(default_factory=dict)
    llm_config: LoopLLMConfig | None = None
    learning: LearningConfig = field(default_factory=LearningConfig)

    def to_summary(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "readiness_level": self.readiness_level,
            "cadence": self.cadence,
            "targets": [target.__dict__ for target in self.targets],
            "source_path": str(self.source_path),
            "paused": self.paused,
            "priority": self.priority,
            "active_windows": list(self.active_windows),
            "max_iterations_per_cycle": self.max_iterations_per_cycle,
            "budget_policy_ref": self.budget_policy_ref,
            "daily_run_cap": self.daily_run_cap,
            "daily_token_cap": self.daily_token_cap,
            "human_gates": list(self.human_gates),
            "denylist": list(self.denylist),
            "checker_policy": dict(self.checker_policy),
            "llm_config": None if self.llm_config is None else self.llm_config.__dict__,
            "learning": {
                **self.learning.__dict__,
                "tournament": self.learning.tournament.__dict__,
                "promotion": self.learning.promotion.__dict__,
            },
        }


def load_loop_profile(
    profile_ref: str, *, profiles_dir: str | Path = "loops/profiles"
) -> LoopProfile:
    profile_path = _resolve_profile_path(profile_ref, Path(profiles_dir))
    if not profile_path.exists():
        raise LoopProfileError(f"Loop profile not found: {profile_ref}")

    load_project_env(anchor=profile_path, override=False)
    payload = _load_payload(profile_path)
    if not isinstance(payload, dict):
        raise LoopProfileError("Loop profile must be a JSON/YAML object/dictionary")
    return parse_loop_profile(payload, source_path=profile_path)


def load_loop_profiles(
    *, profiles_dir: str | Path = "loops/profiles"
) -> list[LoopProfile]:
    directory = Path(profiles_dir)
    profiles: list[LoopProfile] = []
    for path in _profile_paths(directory):
        profiles.append(load_loop_profile(str(path), profiles_dir=directory))
    return profiles


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
    llm_config = (
        _parse_llm_config(llm_payload) if isinstance(llm_payload, dict) else None
    )
    checker_policy = payload.get("checker_policy") or {}
    if not isinstance(checker_policy, dict):
        raise LoopProfileError(
            "checker_policy must be a mapping/dictionary when provided"
        )
    learning = _parse_learning_config(payload.get("learning"), source_path=source_path)

    return LoopProfile(
        profile_id=profile_id,
        readiness_level=readiness_level,
        cadence=cadence,
        targets=targets,
        source_path=source_path.resolve(),
        paused=bool(payload.get("paused", False)),
        priority=int(payload.get("priority", 100)),
        active_windows=[
            str(item).strip()
            for item in (payload.get("active_windows") or [])
            if str(item).strip()
        ],
        max_iterations_per_cycle=max_iterations,
        budget_policy_ref=_optional_str(payload.get("budget_policy_ref")),
        daily_run_cap=_optional_int(payload.get("daily_run_cap")),
        daily_token_cap=_optional_int(payload.get("daily_token_cap")),
        escalation_rules=list(payload.get("escalation_rules") or []),
        human_gates=[str(item) for item in (payload.get("human_gates") or [])],
        denylist=[str(item) for item in (payload.get("denylist") or [])],
        checker_policy=checker_policy,
        llm_config=llm_config,
        learning=learning,
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


def _profile_paths(profiles_dir: Path) -> list[Path]:
    if not profiles_dir.exists():
        return []
    results: list[Path] = []
    for suffix in ("*.yaml", "*.yml", "*.json"):
        results.extend(sorted(profiles_dir.glob(suffix)))
    return results


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
        contract_path = (
            (repo_root / contract).resolve()
            if not Path(contract).is_absolute()
            else Path(contract)
        )
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


def _parse_learning_config(payload: Any, *, source_path: Path) -> LearningConfig:
    if payload is None:
        return LearningConfig()
    if not isinstance(payload, dict):
        raise LoopProfileError("learning must be a mapping/dictionary when provided")

    enabled = bool(payload.get("enabled", False))
    evidence_source = str(payload.get("evidence_source", "synthetic_only")).strip()
    if evidence_source != "synthetic_only":
        raise LoopProfileError("learning.evidence_source must be synthetic_only in v1")
    min_new_runs = int(payload.get("min_new_runs", 3))
    min_new_conversations = int(payload.get("min_new_adversarial_conversations", 100))
    if min_new_runs < 1:
        raise LoopProfileError("learning.min_new_runs must be >= 1")
    if min_new_conversations < 1:
        raise LoopProfileError(
            "learning.min_new_adversarial_conversations must be >= 1"
        )

    raw_kinds = payload.get("candidate_kinds", ["policy", "persona", "scenario"])
    if not isinstance(raw_kinds, list) or not raw_kinds:
        raise LoopProfileError("learning.candidate_kinds must be a non-empty list")
    candidate_kinds = tuple(str(item).strip() for item in raw_kinds)
    allowed_kinds = {"policy", "persona", "scenario"}
    if any(kind not in allowed_kinds for kind in candidate_kinds):
        raise LoopProfileError(
            "learning.candidate_kinds may contain only policy, persona, and scenario"
        )

    validation_contracts = tuple(
        str(item).strip()
        for item in (payload.get("validation_contracts") or [])
        if str(item).strip()
    )
    if enabled and not validation_contracts:
        raise LoopProfileError(
            "learning.validation_contracts is required when learning is enabled"
        )
    repo_root = _find_project_root(source_path.parent)
    for contract in validation_contracts:
        path = Path(contract)
        resolved = path if path.is_absolute() else (repo_root / path)
        if not resolved.exists():
            raise LoopProfileError(
                f"Learning validation contract not found: {contract}"
            )

    if payload.get("require_human_approval", True) is not True:
        raise LoopProfileError("learning.require_human_approval must remain true in v1")

    tournament_payload = payload.get("tournament") or {}
    if not isinstance(tournament_payload, dict):
        raise LoopProfileError("learning.tournament must be a mapping")
    tournament = LearningTournamentConfig(
        initial_pairs=int(tournament_payload.get("initial_pairs", 20)),
        batch_pairs=int(tournament_payload.get("batch_pairs", 20)),
        max_pairs=int(tournament_payload.get("max_pairs", 100)),
    )
    if (
        tournament.initial_pairs < 1
        or tournament.batch_pairs < 1
        or tournament.max_pairs < tournament.initial_pairs
    ):
        raise LoopProfileError(
            "learning tournament pairs must be positive and max_pairs >= initial_pairs"
        )

    promotion_payload = payload.get("promotion") or {}
    if not isinstance(promotion_payload, dict):
        raise LoopProfileError("learning.promotion must be a mapping")
    promotion = LearningPromotionConfig(
        novelty_weight=float(promotion_payload.get("novelty_weight", 0.7)),
        coverage_weight=float(promotion_payload.get("coverage_weight", 0.3)),
        max_detection_drop_points=float(
            promotion_payload.get("max_detection_drop_points", 5.0)
        ),
        max_judge_error_increase_points=float(
            promotion_payload.get("max_judge_error_increase_points", 1.0)
        ),
        max_token_cost_increase_ratio=float(
            promotion_payload.get("max_token_cost_increase_ratio", 0.2)
        ),
    )
    if abs(promotion.novelty_weight + promotion.coverage_weight - 1.0) > 1e-9:
        raise LoopProfileError(
            "learning promotion novelty_weight and coverage_weight must sum to 1"
        )

    return LearningConfig(
        enabled=enabled,
        evidence_source=evidence_source,
        min_new_runs=min_new_runs,
        min_new_adversarial_conversations=min_new_conversations,
        candidate_kinds=candidate_kinds,
        validation_contracts=validation_contracts,
        require_human_approval=True,
        tournament=tournament,
        promotion=promotion,
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


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LoopProfileError(
            f"Expected integer value in loop profile, got: {value}"
        ) from exc


def _required_non_empty(payload: dict[str, Any], key: str) -> str:
    value = _optional_str(payload.get(key))
    if not value:
        raise LoopProfileError(f"Missing required loop profile field: llm_config.{key}")
    return value
