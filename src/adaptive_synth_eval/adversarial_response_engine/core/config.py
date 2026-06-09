"""
YAML-driven experiment config for the adversarial eval harness.

Load a YAML file with load_config(), then override specific fields using
apply_cli_overrides() before passing the result to run_experiment.py.

Example YAML (contracts/example.yaml):

    provider: claude
    scenario_type: data-pii-leak
    budget: 80000
    target:
      endpoint: ${CHATBOT_ENDPOINT}
      timeout_seconds: 45
    judge:
      provider: openai
      model: gpt-4o-mini
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class ComponentConfig:
    provider: Optional[str] = None
    model: Optional[str] = None


@dataclass
class TargetConfig:
    endpoint: str = "mock"
    variant: str = "baseline"
    timeout_seconds: float = 60.0


@dataclass
class StorageConfig:
    backend: str = "local"
    s3_bucket: str = ""
    s3_prefix: str = "adversarial-eval"
    s3_region: str = "us-east-1"
    azure_container: str = ""
    azure_prefix: str = "adversarial-eval"


@dataclass
class TrajectoryConfig:
    """Trajectory-aware evaluation toggle.

    When `enabled`, the harness extracts the target's internal execution trace
    (inline, from `trace_field` in the response body), summarizes it, and judges
    both the final response and the trajectory. When disabled (default), behavior
    is identical to response-only evaluation.
    """
    enabled: bool = False
    trace_field: str = "trace"


@dataclass
class ExperimentConfig:
    provider: str = "mock"
    model: Optional[str] = None
    scenario_type: str = "toxicity"
    budget: int = 100_000
    max_turns: int = 8
    failure_threshold: int = 3
    reserve_tokens: int = 1500
    session_policy: str = "llm"
    no_attack_memory: bool = False
    dry_run: bool = False
    multi_run: bool = False
    verbose: bool = False
    personas: Optional[str] = None
    scenario: Optional[str] = None
    output_dir: str = "results"
    output: Optional[str] = None
    target: TargetConfig = field(default_factory=TargetConfig)
    planner: ComponentConfig = field(default_factory=ComponentConfig)
    generator: ComponentConfig = field(default_factory=ComponentConfig)
    judge: ComponentConfig = field(default_factory=ComponentConfig)
    policy: ComponentConfig = field(default_factory=ComponentConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)


# ---------------------------------------------------------------------------
# Env-var resolution
# ---------------------------------------------------------------------------

def _resolve_env(v: str) -> str:
    """Replace ${VAR_NAME} with the value of that env var (or leave as-is if unset)."""
    return re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.environ.get(m.group(1), m.group(0)),
        v,
    )


def _walk_resolve(obj):
    """Recursively resolve env vars in all string values of a dict/list tree."""
    if isinstance(obj, str):
        return _resolve_env(obj)
    if isinstance(obj, dict):
        return {k: _walk_resolve(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_resolve(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(path: str) -> ExperimentConfig:
    """Parse a YAML file and return an ExperimentConfig with env vars resolved."""
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    raw = _walk_resolve(raw)

    cfg = ExperimentConfig()

    # Top-level scalar fields
    for key in (
            "provider", "model", "scenario_type", "budget", "max_turns",
            "failure_threshold", "reserve_tokens", "session_policy",
            "no_attack_memory", "multi_run", "verbose", "personas",
            "scenario", "output_dir", "output",
    ):
        if key in raw:
            setattr(cfg, key, raw[key])

    # Nested: target
    if "target" in raw:
        t = raw["target"]
        cfg.target = TargetConfig(
            endpoint=t.get("endpoint", cfg.target.endpoint),
            variant=t.get("variant", cfg.target.variant),
            timeout_seconds=float(t.get("timeout_seconds", cfg.target.timeout_seconds)),
        )

    # Nested: per-component overrides
    for attr in ("planner", "generator", "judge", "policy"):
        if attr in raw:
            c = raw[attr]
            setattr(cfg, attr, ComponentConfig(
                provider=c.get("provider"),
                model=c.get("model"),
            ))

    # Nested: storage
    if "storage" in raw:
        s = raw["storage"]
        cfg.storage = StorageConfig(
            backend=s.get("backend", cfg.storage.backend),
            s3_bucket=s.get("s3_bucket", cfg.storage.s3_bucket),
            s3_prefix=s.get("s3_prefix", cfg.storage.s3_prefix),
            s3_region=s.get("s3_region", cfg.storage.s3_region),
            azure_container=s.get("azure_container", cfg.storage.azure_container),
            azure_prefix=s.get("azure_prefix", cfg.storage.azure_prefix),
        )

    return cfg


def apply_cli_overrides(cfg: ExperimentConfig, args) -> None:
    """
    Overwrite config fields with any CLI args that were explicitly set.
    argparse sets all flags to their defaults even if the user didn't pass them,
    so we only override when the CLI value differs from its known default.
    """
    _ARGPARSE_DEFAULTS = {
        "provider": None,  # sentinel: always override if present
        "model": None,
        "target": None,
        "target_variant": "baseline",
        "api_key": None,
        "budget": None,
        "max_turns": 8,
        "failure_threshold": 3,
        "reserve_tokens": 1500,
        "session_policy": "llm",
        "scenario_type": None,
        "output_dir": "results",
        "output": None,
        "verbose": False,
        "multi_run": False,
        "no_attack_memory": False,
        "personas": None,
        "planner_provider": None,
        "planner_model": None,
        "generator_provider": None,
        "generator_model": None,
        "judge_provider": None,
        "judge_model": None,
        "policy_provider": None,
        "policy_model": None,
        "storage": "local",
        "s3_bucket": "",
        "s3_prefix": "adversarial-eval",
        "s3_region": "us-east-1",
        "azure_container": "",
        "azure_prefix": "adversarial-eval",
    }

    def _explicit(attr, default):
        """True when the user actually passed this flag on the CLI."""
        val = getattr(args, attr, None)
        return val is not None and val != default

    if _explicit("provider", _ARGPARSE_DEFAULTS["provider"]):
        cfg.provider = args.provider
    if _explicit("model", _ARGPARSE_DEFAULTS["model"]):
        cfg.model = args.model
    if _explicit("target", _ARGPARSE_DEFAULTS["target"]):
        cfg.target.endpoint = args.target
    if _explicit("target_variant", _ARGPARSE_DEFAULTS["target_variant"]):
        cfg.target.variant = args.target_variant
    if _explicit("budget", _ARGPARSE_DEFAULTS["budget"]):
        cfg.budget = args.budget
    if _explicit("max_turns", _ARGPARSE_DEFAULTS["max_turns"]):
        cfg.max_turns = args.max_turns
    if _explicit("failure_threshold", _ARGPARSE_DEFAULTS["failure_threshold"]):
        cfg.failure_threshold = args.failure_threshold
    if _explicit("reserve_tokens", _ARGPARSE_DEFAULTS["reserve_tokens"]):
        cfg.reserve_tokens = args.reserve_tokens
    if _explicit("session_policy", _ARGPARSE_DEFAULTS["session_policy"]):
        cfg.session_policy = args.session_policy
    if _explicit("scenario_type", _ARGPARSE_DEFAULTS["scenario_type"]):
        cfg.scenario_type = args.scenario_type
    if _explicit("output_dir", _ARGPARSE_DEFAULTS["output_dir"]):
        cfg.output_dir = args.output_dir
    if _explicit("output", _ARGPARSE_DEFAULTS["output"]):
        cfg.output = args.output
    if getattr(args, "verbose", False):
        cfg.verbose = True
    if getattr(args, "multi_run", False):
        cfg.multi_run = True
    if getattr(args, "no_attack_memory", False):
        cfg.no_attack_memory = True
    if _explicit("personas", _ARGPARSE_DEFAULTS["personas"]):
        cfg.personas = args.personas

    # Per-component overrides
    if _explicit("planner_provider", None):
        cfg.planner.provider = args.planner_provider
    if _explicit("planner_model", None):
        cfg.planner.model = args.planner_model
    if _explicit("generator_provider", None):
        cfg.generator.provider = args.generator_provider
    if _explicit("generator_model", None):
        cfg.generator.model = args.generator_model
    if _explicit("judge_provider", None):
        cfg.judge.provider = args.judge_provider
    if _explicit("judge_model", None):
        cfg.judge.model = args.judge_model
    if _explicit("policy_provider", None):
        cfg.policy.provider = args.policy_provider
    if _explicit("policy_model", None):
        cfg.policy.model = args.policy_model

    # Storage
    if _explicit("storage", _ARGPARSE_DEFAULTS["storage"]):
        cfg.storage.backend = args.storage
    if _explicit("s3_bucket", _ARGPARSE_DEFAULTS["s3_bucket"]):
        cfg.storage.s3_bucket = args.s3_bucket
    if _explicit("s3_prefix", _ARGPARSE_DEFAULTS["s3_prefix"]):
        cfg.storage.s3_prefix = args.s3_prefix
    if _explicit("s3_region", _ARGPARSE_DEFAULTS["s3_region"]):
        cfg.storage.s3_region = args.s3_region
    if _explicit("azure_container", _ARGPARSE_DEFAULTS["azure_container"]):
        cfg.storage.azure_container = args.azure_container
    if _explicit("azure_prefix", _ARGPARSE_DEFAULTS["azure_prefix"]):
        cfg.storage.azure_prefix = args.azure_prefix
