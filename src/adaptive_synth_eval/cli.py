from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from adaptive_synth_eval.adversarial_response_engine.skills.registry import (
    SkillValidationError,
    get_builtin_registry,
)
from adaptive_synth_eval.artifacts.run_state import (
    clear_run_directory,
    detect_incomplete_run,
)
from adaptive_synth_eval.clients.logger_utils import setup_logger
from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.config.env import load_project_env
from adaptive_synth_eval.engines.chat_history_simulation import run_simulation
from adaptive_synth_eval.evaluation.modes import get_mode
from adaptive_synth_eval.live_status import LiveStatusBar
from adaptive_synth_eval.loop.audit import build_loop_audit
from adaptive_synth_eval.loop.planner import LoopReasoner
from adaptive_synth_eval.loop.policy import LoopPolicyEngine
from adaptive_synth_eval.loop.profiles import (
    LoopProfileError,
    load_loop_profile,
    load_loop_profiles,
)
from adaptive_synth_eval.loop.scheduler import LoopScheduler, MultiLoopCoordinator
from adaptive_synth_eval.loop.state_store import (
    get_loop_status,
    initialize_loop_assets,
    record_loop_cycle,
    set_loop_paused,
)
from adaptive_synth_eval.loop.verifier import LoopVerifier
from adaptive_synth_eval.monitoring import run_monitoring
from adaptive_synth_eval.prompt_toolkit_status import PromptToolkitStatusBar

logger = setup_logger(__name__)

_CONFIG_BLOCK_SEPARATOR = "=" * 90


def _format_llm_spec(spec: Any) -> str:
    provider = getattr(spec, "provider", "unknown") or "unknown"
    model = getattr(spec, "model", "") or "default"
    temp = getattr(spec, "temperature", None)
    max_tokens = getattr(spec, "max_tokens", None)
    parts = [f"provider={provider}", f"model={model}"]
    if temp is not None:
        parts.append(f"temperature={temp}")
    if max_tokens is not None:
        parts.append(f"max_tokens={max_tokens}")
    return ", ".join(parts)


def _describe_target(contract: Any) -> str:
    target = getattr(contract, "target", None)
    if target is None:
        return "target=unknown"

    mode = getattr(target, "mode", "api") or "api"
    enabled = getattr(target, "enabled", True)
    details = [f"enabled={enabled}", f"mode={mode}"]

    endpoint = getattr(target, "endpoint", None)
    if endpoint:
        details.append(f"endpoint={endpoint}")

    browser = getattr(target, "browser", None)
    if browser is not None and getattr(browser, "url", None):
        details.append(f"url={browser.url}")

    agentcore = getattr(target, "agentcore", None)
    if agentcore is not None:
        if getattr(agentcore, "region", None):
            details.append(f"region={agentcore.region}")
        if getattr(agentcore, "agent_runtime_arn", None):
            details.append(f"agent_runtime_arn={agentcore.agent_runtime_arn}")
        if getattr(agentcore, "qualifier", None):
            details.append(f"qualifier={agentcore.qualifier}")

    target_llm = getattr(contract, "target_llm", None)
    if mode == "llm" and target_llm is not None:
        details.append(f"chatbot_llm=({_format_llm_spec(target_llm)})")

    return ", ".join(details)


def _describe_target_runtime_source(contract: Any) -> str:
    target = getattr(contract, "target", None)
    mode = getattr(target, "mode", "api") if target is not None else "unknown"
    if mode == "llm":
        return "source=adaptive_synth_eval.unified_eval.providers.llm_target_client.LLMTargetClient"
    return "source=adaptive_synth_eval.clients.chatbot_factory.create_chatbot_client"


def _describe_synth_persona_runtime() -> str:
    return (
        "source=adaptive_synth_eval.generation.turns.UserSimulator -> "
        "adaptive_synth_eval.clients.llm.LLMClient, "
        "provider_resolution=environment auto-detect, "
        "fallback=template-based generation when no supported provider is configured"
    )


def _describe_unified_persona_runtime() -> str:
    return "source=adaptive_synth_eval.unified_eval.providers.llm_factory.build_component_llms"


def _unified_component_runtime_note(component: str, spec: Any) -> str | None:
    provider = (getattr(spec, "provider", "") or "").lower()
    if component == "user_simulator" and provider == "bedrock":
        return "effective_runtime=mock synth adapter (Bedrock synth adapter not implemented)"
    return None


def _build_run_configuration_lines(
    contract: Any,
    *,
    mode_name: str,
    contract_path: str,
    dry_run: bool,
    persona_filter: str | None,
    scenario_filter: str | None = None,
    adversarial_filter: str | None = None,
    max_concurrency_override: int | None = None,
    realtime_chat: bool = False,
) -> list[str]:
    lines = [
        _CONFIG_BLOCK_SEPARATOR,
        "Planned run configuration start",
        (
            "Run configuration: "
            f"contract={contract_path}, mode={mode_name}, dry_run={dry_run}, "
            f"realtime_chat={realtime_chat}, persona_filter={persona_filter or '*'}"
        ),
    ]

    if mode_name == "synth":
        suite = contract.simulation_suite
        traffic = contract.traffic
        lines.append(
            "Synth contract: "
            f"suite_id={suite.suite_id}, target_application={suite.target_application}, "
            f"planned_conversations={traffic.total_conversations}, "
            f"turns_per_conversation={traffic.conversation_turns.min}-{traffic.conversation_turns.max}, "
            f"max_concurrency={traffic.max_concurrency}"
        )
        lines.append(f"Target runtime: {_describe_target_runtime_source(contract)}")
        lines.append(f"Target: {_describe_target(contract)}")
        lines.append(f"Human persona simulation: {_describe_synth_persona_runtime()}")
        lines.append("Planned run configuration end")
        lines.append(_CONFIG_BLOCK_SEPARATOR)
        return lines

    suite = contract.suite
    effective_max_concurrency = max_concurrency_override or contract.run.max_concurrency
    total_conversations = contract.eval_plan.total_conversations
    conversation_turns = contract.eval_plan.conversation_turns
    lines.append(
        "Unified contract: "
        f"suite_id={suite.suite_id}, target_application={suite.target_application}, "
        f"planned_conversations={total_conversations if total_conversations is not None else 'budget-driven'}, "
        f"turns_per_conversation={conversation_turns.min}-{conversation_turns.max}, "
        f"max_concurrency={effective_max_concurrency}, "
        f"synth_scenarios={len(contract.scenario_catalog)}, adversarial_scenarios={len(contract.adversarial_scenario_catalog)}"
    )
    lines.append(f"Target runtime: {_describe_target_runtime_source(contract)}")
    lines.append(f"Target: {_describe_target(contract)}")
    lines.append(f"Human persona simulation: {_describe_unified_persona_runtime()}")
    if scenario_filter or adversarial_filter:
        lines.append(
            "Run filters: "
            f"synth_scenario={scenario_filter or '*'}, adversarial_scenario={adversarial_filter or '*'}"
        )

    lines.append(f"Harness default LLM: {_format_llm_spec(contract.llm)}")
    for component in ("planner", "generator", "judge", "policy", "user_simulator"):
        spec = contract.llm_for(component)
        line = f"Adaptive component {component}: {_format_llm_spec(spec)}"
        runtime_note = _unified_component_runtime_note(component, spec)
        if runtime_note:
            line = f"{line}, {runtime_note}"
        lines.append(line)
    lines.append("Planned run configuration end")
    lines.append(_CONFIG_BLOCK_SEPARATOR)
    return lines


def _log_run_configuration(
    contract: Any,
    *,
    mode_name: str,
    contract_path: str,
    dry_run: bool,
    persona_filter: str | None,
    scenario_filter: str | None = None,
    adversarial_filter: str | None = None,
    max_concurrency_override: int | None = None,
    realtime_chat: bool = False,
) -> None:
    for line in _build_run_configuration_lines(
        contract,
        mode_name=mode_name,
        contract_path=contract_path,
        dry_run=dry_run,
        persona_filter=persona_filter,
        scenario_filter=scenario_filter,
        adversarial_filter=adversarial_filter,
        max_concurrency_override=max_concurrency_override,
        realtime_chat=realtime_chat,
    ):
        logger.info(line)


def _run_with_live_status(
    *,
    title: str,
    enabled: bool,
    realtime_interactive: bool,
    runner,
) -> dict[str, Any]:
    if realtime_interactive:
        try:
            from prompt_toolkit import PromptSession  # noqa: F401
        except Exception as exc:  # pragma: no cover - runtime dependency check
            raise ContractError(
                "Realtime interactive mode with pinned bottom status bar requires prompt_toolkit. "
                "Install dependencies (for example: uv sync or pip install prompt_toolkit) and retry."
            ) from exc
        status_renderer: Any = PromptToolkitStatusBar(title=title, enabled=enabled)
    else:
        status_renderer = LiveStatusBar(title=title, enabled=enabled)

    started = status_renderer.start()

    def _progress_sink(payload: dict[str, Any]) -> None:
        status_renderer.update(**payload)

    try:
        return runner(
            _progress_sink if status_renderer.enabled else None, status_renderer
        )
    finally:
        if started:
            status_renderer.update(phase="complete")
        status_renderer.stop()


def detect_mode_from_file(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        raise ContractError(f"Contract file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)

        if not isinstance(payload, dict):
            raise ContractError("Contract must be a JSON/YAML object/dictionary")

        is_unified = "suite" in payload and "eval_plan" in payload
        is_synth = "simulation_suite" in payload and "traffic_orchestration" in payload

        if is_unified and is_synth:
            raise ContractError(
                "Contract contains both synth and unified top-level structures."
            )
        if is_unified:
            return "unified"
        if is_synth:
            return "synth"
        raise ContractError(
            "Contract must be either synth or unified format (missing key fields: "
            "suite/eval_plan/adversarial_scenario_catalog for unified, or "
            "simulation_suite/traffic_orchestration for synth)"
        )
    except Exception as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError(f"Failed to parse contract file: {exc}")


def main(argv: list[str] | None = None) -> int:
    load_project_env(anchor=Path.cwd())
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "skills":
            registry = get_builtin_registry()
            if args.skills_command == "list":
                payload = [
                    {
                        "name": skill.name,
                        "description": skill.description,
                        "compatibility": skill.compatibility,
                        "angle": skill.angle,
                        "version": skill.version,
                        "digest": skill.package_digest,
                        "allowed_tools": list(skill.allowed_tools),
                    }
                    for skill in registry.skills
                ]
                if args.json:
                    print(json.dumps(payload, indent=2))
                else:
                    for item in payload:
                        print(
                            f"{item['name']}\t{item['version']}\t"
                            f"{item['angle']}\t{item['digest'][:12]}"
                        )
                return 0

            if args.skills_command == "show":
                skill = registry.get(args.name)
                payload = {
                    "name": skill.name,
                    "description": skill.description,
                    "compatibility": skill.compatibility,
                    "angle": skill.angle,
                    "version": skill.version,
                    "sub_tactics": list(skill.sub_tactics),
                    "accumulation": skill.accumulation,
                    "scenario_types": list(skill.scenario_types),
                    "allowed_tools": list(skill.allowed_tools),
                    "digest": skill.package_digest,
                    "instructions": skill.instructions,
                }
                if args.json:
                    print(json.dumps(payload, indent=2))
                else:
                    print(skill.instructions)
                return 0

            if args.skills_command == "validate":
                selected = (registry.get(args.name),) if args.name else registry.skills
                for skill in selected:
                    print(f"Valid skill: {skill.name} ({skill.package_digest[:12]})")
                return 0

        if args.command == "loop":
            if args.loop_command == "init":
                profile = load_loop_profile(
                    args.profile, profiles_dir=args.profiles_dir
                )
                summary = initialize_loop_assets(
                    profile, output_dir=Path(args.output_dir)
                )
                print(json.dumps(summary, indent=2, default=str))
                return 0

            if args.loop_command == "run":
                profile = load_loop_profile(
                    args.profile, profiles_dir=args.profiles_dir
                )
                summary = _run_loop_profile(
                    profile,
                    output_dir=Path(args.output_dir),
                    dry_run=args.dry_run,
                    incomplete_run_action=args.incomplete_run_action,
                    realtime_chat=args.realtime_chat,
                    output_conversations=args.output_conversations,
                )
                print(json.dumps(summary, indent=2, default=str))
                return 0

            if args.loop_command == "start":
                output_dir = Path(args.output_dir)
                profiles_dir = Path(args.profiles_dir)
                if args.all:
                    profiles = load_loop_profiles(profiles_dir=profiles_dir)
                    if not profiles:
                        raise LoopProfileError(
                            f"No loop profiles found in: {profiles_dir}"
                        )
                    coordinator = MultiLoopCoordinator()
                    summary = coordinator.run_profiles(
                        profiles,
                        cycle_fn=lambda profile: _run_loop_profile(
                            profile,
                            output_dir=output_dir,
                            dry_run=args.dry_run,
                            incomplete_run_action=args.incomplete_run_action,
                            realtime_chat=args.realtime_chat,
                            output_conversations=args.output_conversations,
                        ),
                        state_fn=lambda profile: get_loop_status(
                            profile_ref=profile.profile_id,
                            output_dir=output_dir,
                            profiles_dir=profiles_dir,
                        ),
                        once=args.once,
                        max_rounds=args.max_cycles,
                        interval_seconds_override=args.interval_seconds,
                    )
                else:
                    if not args.profile:
                        raise LoopProfileError(
                            "loop start requires --profile <id> or --all"
                        )
                    profile = load_loop_profile(
                        args.profile, profiles_dir=args.profiles_dir
                    )
                    scheduler = LoopScheduler()
                    summary = scheduler.run_profile(
                        profile,
                        cycle_fn=lambda: _run_loop_profile(
                            profile,
                            output_dir=output_dir,
                            dry_run=args.dry_run,
                            incomplete_run_action=args.incomplete_run_action,
                            realtime_chat=args.realtime_chat,
                            output_conversations=args.output_conversations,
                        ),
                        state_fn=lambda current_profile: get_loop_status(
                            profile_ref=current_profile.profile_id,
                            output_dir=output_dir,
                            profiles_dir=profiles_dir,
                        ),
                        once=args.once,
                        max_cycles=args.max_cycles,
                        interval_seconds_override=args.interval_seconds,
                    )
                print(json.dumps(summary, indent=2, default=str))
                return 0

            if args.loop_command == "status":
                status = get_loop_status(
                    profile_ref=args.profile,
                    output_dir=Path(args.output_dir),
                    profiles_dir=Path(args.profiles_dir),
                )
                print(json.dumps(status, indent=2, default=str))
                return 0

            if args.loop_command == "audit":
                report = build_loop_audit(
                    profile_ref=args.profile,
                    output_dir=Path(args.output_dir),
                    profiles_dir=Path(args.profiles_dir),
                )
                print(json.dumps(report, indent=2, default=str))
                return 0

            if args.loop_command == "pause":
                state = set_loop_paused(
                    args.profile,
                    paused=True,
                    reason=args.reason,
                    output_dir=Path(args.output_dir),
                    profiles_dir=Path(args.profiles_dir),
                )
                print(json.dumps(state, indent=2, default=str))
                return 0

            if args.loop_command == "resume":
                state = set_loop_paused(
                    args.profile,
                    paused=False,
                    output_dir=Path(args.output_dir),
                    profiles_dir=Path(args.profiles_dir),
                )
                print(json.dumps(state, indent=2, default=str))
                return 0

        if args.command == "validate-contract":
            mode_name = detect_mode_from_file(args.contract)
            mode = get_mode(mode_name)
            contract = mode.load_contract(args.contract)
            for warning in getattr(contract, "warnings", []):
                logger.warning(warning)
            logger.info("Contract valid")
            print("Contract valid")
            return 0

        if args.command == "run":
            summary = _execute_contract_run(
                contract_path=args.contract,
                dry_run=args.dry_run,
                persona_filter=args.persona,
                scenario_filter=getattr(args, "scenario", None),
                adversarial_filter=getattr(args, "adversarial_scenario", None),
                max_concurrency_override=getattr(args, "max_concurrency", None),
                run_id_override=getattr(args, "run_id", None),
                realtime_chat=args.realtime_chat,
                output_conversations=args.output_conversations,
                interactive_realtime_controls=args.interactive_realtime_controls,
                incomplete_run_action=args.incomplete_run_action,
            )

            logger.info("Run complete: %s", summary["run_id"])
            logger.info(json.dumps(summary, indent=2, default=str))
            print(f"Run complete: {summary['run_id']}")
            return 0

        if args.command == "summarize":
            summary_path = (
                Path(args.output_dir) / "runs" / args.run_id / "run_summary.json"
            )
            if not summary_path.exists():
                logger.error("Run summary not found: %s", summary_path)
                return 2
            print(summary_path.read_text(encoding="utf-8"))
            return 0

        if args.command == "metrics":
            if args.metrics_command == "serve":
                import uvicorn

                uvicorn.run(
                    "adaptive_synth_eval.metrics_api.app:create_app",
                    factory=True,
                    host=args.host,
                    port=args.port,
                    workers=args.workers,
                )
                return 0

        if args.command == "monitor":
            if args.monitor_command == "run":
                run_dir = Path(args.run_folder)
                metrics_config_path = (
                    Path(args.metrics_config) if args.metrics_config else None
                )
                summary = run_monitoring(
                    run_dir=run_dir,
                    sample_size=args.sample_size,
                    interval_minutes=args.interval_minutes,
                    sampling_strategy=args.sampling_strategy,
                    incomplete_run_action=args.incomplete_run_action,
                    dry_run=args.dry_run,
                    max_windows=args.max_windows,
                    metrics_config_path=metrics_config_path,
                    rescan=args.rescan,
                    triggered_lookback=args.triggered_lookback,
                    triggered_lookahead=args.triggered_lookahead,
                    trigger_policy_path=(
                        Path(args.trigger_policy) if args.trigger_policy else None
                    ),
                )
                print(json.dumps(summary, indent=2, default=str))
                return 0

        parser.print_help()
        return 1
    except (ContractError, LoopProfileError, SkillValidationError) as exc:
        logger.error(str(exc))
        print(str(exc), file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ase",
        description=(
            "Generate synthetic multi-turn chat history data for chatbot evaluation. "
            "Use subcommands to validate a contract, run a simulation, summarize a prior run, "
            "manage loop assets, or evaluate existing run artifacts for monitoring."
        ),
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        description="Available operations",
        metavar="{validate-contract,run,summarize,skills,loop,monitor,metrics}",
    )
    skills = sub.add_parser(
        "skills",
        help="Inspect and validate curated attack-method skills",
        description="List, show, or validate packaged Agent Skills used by adversarial evaluation.",
    )
    skills_sub = skills.add_subparsers(
        dest="skills_command",
        required=True,
        title="skills commands",
        metavar="{list,show,validate}",
    )
    skills_list = skills_sub.add_parser("list", help="List packaged attack skills")
    skills_list.add_argument("--json", action="store_true", help="Emit JSON")
    skills_show = skills_sub.add_parser("show", help="Show one packaged attack skill")
    skills_show.add_argument("name", help="Skill name")
    skills_show.add_argument("--json", action="store_true", help="Emit JSON")
    skills_validate = skills_sub.add_parser(
        "validate", help="Validate one skill or the entire packaged catalog"
    )
    skills_validate.add_argument("name", nargs="?", help="Optional skill name")

    validate = sub.add_parser(
        "validate-contract",
        help="Validate a simulation contract file and report schema or config issues",
        description="Validate a simulation contract file and print warnings if present.",
    )
    validate.add_argument(
        "contract", help="Path to a YAML/JSON simulation contract file"
    )

    run = sub.add_parser(
        "run",
        help="Run a synthetic or unified chat simulation from a contract",
        description="Execute a simulation run from a contract and write artifacts to outputs/runs/<run_id>/.",
    )
    run.add_argument(
        "--contract", required=True, help="Path to a YAML/JSON simulation contract file"
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip real chatbot calls and use mock responses",
    )
    run.add_argument(
        "--output-conversations",
        action="store_true",
        help="Output conversations in human-readable format with Persona/Bot labels",
    )
    run.add_argument(
        "--realtime-chat",
        action="store_true",
        help="Stream persona and chatbot messages to console in real time",
    )
    run.add_argument(
        "--interactive-realtime-controls",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable runtime controls during --realtime-chat (synth mode only, default: enabled with --realtime-chat). "
            "Use --no-interactive-realtime-controls to disable."
        ),
    )
    run.add_argument(
        "--persona",
        help="Limit/filter the simulation run to only a specific persona ID.",
    )
    # Unified mode-specific arguments
    run.add_argument(
        "--scenario",
        help="Filter to a single synth scenario_id (unified contracts only)",
    )
    run.add_argument(
        "--adversarial-scenario",
        help="Filter to a single adversarial scenario_id (unified contracts only)",
    )
    run.add_argument(
        "--max-concurrency",
        type=int,
        default=None,
        help="Override eval_plan max_concurrency (unified contracts only)",
    )
    run.add_argument(
        "--run-id",
        help="Override the run_id (unified contracts only)",
    )
    run.add_argument(
        "--incomplete-run-action",
        choices=("ask", "resume", "restart", "abort"),
        default="ask",
        help=(
            "Action when an existing run directory appears incomplete. "
            "'resume' continues remaining conversations, 'restart' clears prior artifacts and starts over, "
            "'abort' exits, 'ask' prompts interactively (default)."
        ),
    )

    summarize = sub.add_parser(
        "summarize",
        help="Print run_summary.json for a previous run",
        description="Load and print the summary JSON for an existing run.",
    )
    summarize.add_argument("--run-id", required=True, help="Run ID to summarize")
    summarize.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory that contains runs/<run_id>/run_summary.json (default: outputs)",
    )

    metrics = sub.add_parser(
        "metrics",
        help="Serve packaged metric specifications and standalone evaluation",
        description="Run the authenticated stateless metrics REST API.",
    )
    metrics_sub = metrics.add_subparsers(
        dest="metrics_command",
        required=True,
        title="metrics commands",
        metavar="{serve}",
    )
    metrics_serve = metrics_sub.add_parser(
        "serve",
        help="Launch the standalone metrics FastAPI service",
    )
    metrics_serve.add_argument("--host", default="127.0.0.1")
    metrics_serve.add_argument("--port", type=int, default=8000)
    metrics_serve.add_argument("--workers", type=int, default=1)

    monitor = sub.add_parser(
        "monitor",
        help="Evaluate existing chat history artifacts for continuous monitoring",
        description=(
            "Run monitoring evaluation over outputs/runs/<run_id>/chat_history.jsonl in sampling windows, "
            "persisting resumable state and auto-versioned scores via evaluation fingerprints."
        ),
    )
    monitor_sub = monitor.add_subparsers(
        dest="monitor_command",
        required=True,
        title="monitor commands",
        description="Monitoring operations",
        metavar="{run}",
    )

    monitor_run = monitor_sub.add_parser(
        "run",
        help="Evaluate chat_history.jsonl in a run folder using sampling windows",
        description=(
            "Load run-folder chat history artifacts, evaluate in configurable windows, "
            "and append dashboard-oriented records into monitoring_scores.jsonl."
        ),
    )
    monitor_run.add_argument(
        "--run-folder",
        required=True,
        help="Path to an existing outputs/runs/<run_id> folder that contains chat_history.jsonl",
    )
    monitor_run.add_argument(
        "--sample-size",
        type=int,
        default=1000,
        help=(
            "Rows to evaluate per sampling window; this is the hard capture "
            "budget for triggered sampling (default: 1000)"
        ),
    )
    monitor_run.add_argument(
        "--interval-minutes",
        type=int,
        default=60,
        help="Sampling window interval metadata in minutes (default: 60)",
    )
    monitor_run.add_argument(
        "--sampling-strategy",
        choices=("all", "random", "systematic", "triggered"),
        default="all",
        help="Sampling strategy to select subset of chats per window (default: all)",
    )
    monitor_run.add_argument(
        "--triggered-lookback",
        type=int,
        default=2,
        help="Lookback turns to include in context when trigger fires (default: 2). Used with --sampling-strategy triggered.",
    )
    monitor_run.add_argument(
        "--triggered-lookahead",
        type=int,
        default=2,
        help="Lookahead turns to hold pending when trigger fires (default: 2). Used with --sampling-strategy triggered.",
    )
    monitor_run.add_argument(
        "--trigger-policy",
        default=None,
        help="Optional YAML policy that completely replaces the packaged trigger policy.",
    )
    monitor_run.add_argument(
        "--max-windows",
        type=int,
        default=None,
        help="Optional cap on windows processed in a single invocation.",
    )
    monitor_run.add_argument(
        "--rescan",
        action="store_true",
        help="Rescan source history from the beginning while reusing fingerprint-valid scores.",
    )
    monitor_run.add_argument(
        "--metrics-config",
        default=None,
        help="Optional path to a custom metrics.yaml (for testing).",
    )
    monitor_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip live LLM calls and use deterministic local scoring for test runs.",
    )
    monitor_run.add_argument(
        "--incomplete-run-action",
        choices=("ask", "resume", "restart", "abort"),
        default="ask",
        help=(
            "Action when monitoring_state.json is not completed. "
            "'resume' continues progress, 'restart' starts over, 'abort' exits, 'ask' prompts interactively."
        ),
    )

    loop = sub.add_parser(
        "loop",
        help="Initialize and inspect persistent loop assets",
        description="Manage loop profile state under outputs/loops without affecting simulation runs.",
    )
    loop_sub = loop.add_subparsers(
        dest="loop_command",
        required=True,
        title="loop commands",
        description="Loop operations",
        metavar="{init,run,start,status,audit,pause,resume}",
    )

    loop_init = loop_sub.add_parser(
        "init",
        help="Initialize persistent assets for a loop profile",
        description="Create loop state and markdown guardrail artifacts for a checked-in loop profile.",
    )
    loop_init.add_argument(
        "--profile",
        required=True,
        help="Loop profile ID or path to a profile YAML/JSON file",
    )
    loop_init.add_argument(
        "--profiles-dir",
        default="loops/profiles",
        help="Directory containing checked-in loop profiles (default: loops/profiles)",
    )
    loop_init.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory for loop state and markdown artifacts (default: outputs)",
    )

    loop_run = loop_sub.add_parser(
        "run",
        help="Execute a report-only loop cycle for a profile",
        description="Run the profile's configured targets through the existing ase run internals and persist cycle state.",
    )
    loop_run.add_argument(
        "--profile",
        required=True,
        help="Loop profile ID or path to a profile YAML/JSON file",
    )
    loop_run.add_argument(
        "--profiles-dir",
        default="loops/profiles",
        help="Directory containing checked-in loop profiles (default: loops/profiles)",
    )
    loop_run.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory for loop state and markdown artifacts (default: outputs)",
    )
    loop_run.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run loop targets in dry-run mode by default. Use --no-dry-run to allow live target calls.",
    )
    loop_run.add_argument(
        "--output-conversations",
        action="store_true",
        help="Output conversations in human-readable format for each target run when supported.",
    )
    loop_run.add_argument(
        "--realtime-chat",
        action="store_true",
        help="Stream persona and chatbot messages in real time for each target run.",
    )
    loop_run.add_argument(
        "--incomplete-run-action",
        choices=("ask", "resume", "restart", "abort"),
        default="abort",
        help="Action when a target run directory appears incomplete (default: abort).",
    )

    loop_start = loop_sub.add_parser(
        "start",
        help="Start a recurring loop scheduler for a profile",
        description="Run the profile's loop cycle once or on its configured cadence and persist reasoning/state updates.",
    )
    loop_start.add_argument(
        "--profile", help="Loop profile ID or path to a profile YAML/JSON file"
    )
    loop_start.add_argument(
        "--all",
        action="store_true",
        help="Run all checked-in loop profiles using the multi-profile coordinator.",
    )
    loop_start.add_argument(
        "--profiles-dir",
        default="loops/profiles",
        help="Directory containing checked-in loop profiles (default: loops/profiles)",
    )
    loop_start.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory for loop state and markdown artifacts (default: outputs)",
    )
    loop_start.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run loop targets in dry-run mode by default. Use --no-dry-run to allow live target calls.",
    )
    loop_start.add_argument(
        "--output-conversations",
        action="store_true",
        help="Output conversations in human-readable format for each target run when supported.",
    )
    loop_start.add_argument(
        "--realtime-chat",
        action="store_true",
        help="Stream persona and chatbot messages in real time for each target run.",
    )
    loop_start.add_argument(
        "--incomplete-run-action",
        choices=("ask", "resume", "restart", "abort"),
        default="abort",
        help="Action when a target run directory appears incomplete (default: abort).",
    )
    loop_start.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle immediately and exit.",
    )
    loop_start.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Optional safety cap on recurring cycles before exiting.",
    )
    loop_start.add_argument(
        "--interval-seconds",
        type=float,
        default=None,
        help="Override the cadence-derived interval in seconds, mainly for testing or manual control.",
    )

    loop_status = loop_sub.add_parser(
        "status",
        help="Inspect persisted loop state",
        description="Print initialized loop state summaries from outputs/loops.",
    )
    loop_status.add_argument("--profile", help="Optional loop profile ID to inspect")
    loop_status.add_argument(
        "--profiles-dir",
        default="loops/profiles",
        help="Directory containing checked-in loop profiles (default: loops/profiles)",
    )
    loop_status.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory for loop state and markdown artifacts (default: outputs)",
    )

    loop_audit = loop_sub.add_parser(
        "audit",
        help="Produce a loop readiness and safeguards audit report",
        description="Evaluate loop profile readiness controls and persisted loop artifacts for L0-L3 progression.",
    )
    loop_audit.add_argument("--profile", help="Optional loop profile ID to audit")
    loop_audit.add_argument(
        "--profiles-dir",
        default="loops/profiles",
        help="Directory containing checked-in loop profiles (default: loops/profiles)",
    )
    loop_audit.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory for loop state and markdown artifacts (default: outputs)",
    )

    loop_pause = loop_sub.add_parser(
        "pause",
        help="Pause a loop profile via persistent kill switch state",
        description="Set paused=true in loop state so unattended schedulers skip the profile until resumed.",
    )
    loop_pause.add_argument(
        "--profile",
        required=True,
        help="Loop profile ID or path to a profile YAML/JSON file",
    )
    loop_pause.add_argument(
        "--reason",
        default="manual pause",
        help="Reason recorded in loop state and run log",
    )
    loop_pause.add_argument(
        "--profiles-dir",
        default="loops/profiles",
        help="Directory containing checked-in loop profiles (default: loops/profiles)",
    )
    loop_pause.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory for loop state and markdown artifacts (default: outputs)",
    )

    loop_resume = loop_sub.add_parser(
        "resume",
        help="Resume a paused loop profile",
        description="Clear paused state so unattended schedulers can run the profile again.",
    )
    loop_resume.add_argument(
        "--profile",
        required=True,
        help="Loop profile ID or path to a profile YAML/JSON file",
    )
    loop_resume.add_argument(
        "--profiles-dir",
        default="loops/profiles",
        help="Directory containing checked-in loop profiles (default: loops/profiles)",
    )
    loop_resume.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory for loop state and markdown artifacts (default: outputs)",
    )
    return parser


def _resolve_run_dir(
    contract: Any, *, mode_name: str, run_id_override: str | None
) -> Path | None:
    output = getattr(contract, "output", None)
    if output is None:
        return None

    base_dir = getattr(output, "base_dir", None)
    if base_dir is None:
        return None

    run_id = (
        run_id_override
        if mode_name == "unified" and run_id_override
        else getattr(output, "run_id", None)
    )
    if not run_id:
        return None
    return Path(base_dir) / "runs" / run_id


def _execute_contract_run(
    *,
    contract_path: str,
    dry_run: bool,
    persona_filter: str | None,
    scenario_filter: str | None,
    adversarial_filter: str | None,
    max_concurrency_override: int | None,
    run_id_override: str | None,
    realtime_chat: bool,
    output_conversations: bool,
    interactive_realtime_controls: bool | None,
    incomplete_run_action: str,
) -> dict[str, Any]:
    mode_name = detect_mode_from_file(contract_path)
    mode = get_mode(mode_name)
    contract = mode.load_contract(contract_path)
    _log_run_configuration(
        contract,
        mode_name=mode_name,
        contract_path=contract_path,
        dry_run=dry_run,
        persona_filter=persona_filter,
        scenario_filter=scenario_filter,
        adversarial_filter=adversarial_filter,
        max_concurrency_override=max_concurrency_override,
        realtime_chat=realtime_chat,
    )

    run_dir = _resolve_run_dir(
        contract, mode_name=mode_name, run_id_override=run_id_override
    )
    resume_incomplete = False
    if run_dir is not None:
        incomplete = detect_incomplete_run(run_dir)
        if incomplete is not None:
            action = _resolve_incomplete_action(
                incomplete_run_action, run_dir, incomplete
            )
            if action == "abort":
                raise ContractError(
                    "Detected an incomplete prior run. Re-run with "
                    "--incomplete-run-action resume or --incomplete-run-action restart."
                )
            if action == "restart":
                logger.warning(
                    "Cleaning existing run artifacts before starting a new run: %s",
                    run_dir,
                )
                clear_run_directory(run_dir)
            elif action == "resume":
                logger.warning(
                    "Resuming incomplete run from existing artifacts: %s", run_dir
                )
                resume_incomplete = True

    if mode_name == "synth":
        unified_flags = []
        if scenario_filter is not None:
            unified_flags.append("--scenario")
        if adversarial_filter is not None:
            unified_flags.append("--adversarial-scenario")
        if max_concurrency_override is not None:
            unified_flags.append("--max-concurrency")
        if run_id_override is not None:
            unified_flags.append("--run-id")
        if unified_flags:
            raise ContractError(
                f"Unified-only flags {', '.join(unified_flags)} cannot be used with a synth-only contract."
            )

        controls_enabled = interactive_realtime_controls
        if controls_enabled is None:
            controls_enabled = realtime_chat
        live_status_enabled = sys.stdout.isatty()
        return _run_with_live_status(
            title="ASE RUN",
            enabled=live_status_enabled,
            realtime_interactive=realtime_chat and controls_enabled,
            runner=lambda progress_sink, status_renderer: run_simulation(
                contract,
                dry_run=dry_run,
                output_conversations=output_conversations,
                realtime_chat=realtime_chat,
                interactive_realtime_controls=controls_enabled,
                persona_filter=persona_filter,
                resume_incomplete=resume_incomplete,
                progress_sink=progress_sink,
                realtime_status_provider=status_renderer
                if (realtime_chat and controls_enabled)
                else None,
            ),
        )

    controls_enabled = interactive_realtime_controls
    if controls_enabled is None:
        controls_enabled = realtime_chat
    live_status_enabled = sys.stdout.isatty()
    return _run_with_live_status(
        title="ASE RUN",
        enabled=live_status_enabled,
        realtime_interactive=realtime_chat and controls_enabled,
        runner=lambda progress_sink, status_renderer: mode.run(
            contract,
            dry_run=dry_run,
            persona_filter=persona_filter,
            scenario_filter=scenario_filter,
            adversarial_filter=adversarial_filter,
            max_concurrency_override=max_concurrency_override,
            run_id_override=run_id_override,
            realtime_chat=realtime_chat,
            output_conversations=output_conversations,
            interactive_realtime_controls=controls_enabled,
            resume_incomplete=resume_incomplete,
            progress_sink=progress_sink,
            realtime_status_provider=status_renderer
            if (realtime_chat and controls_enabled)
            else None,
        ),
    )


def _run_loop_profile(
    profile: Any,
    *,
    output_dir: Path,
    dry_run: bool,
    incomplete_run_action: str,
    realtime_chat: bool,
    output_conversations: bool,
) -> dict[str, Any]:
    initialize_loop_assets(profile, output_dir=output_dir)
    loop_state = get_loop_status(profile_ref=profile.profile_id, output_dir=output_dir)
    _enforce_l3_preflight(profile, loop_state, output_dir=output_dir)
    loop_state = get_loop_status(profile_ref=profile.profile_id, output_dir=output_dir)
    reasoner = LoopReasoner(profile)
    policy_engine = LoopPolicyEngine(profile)
    verifier = LoopVerifier(profile)
    planner_decision = reasoner.plan_cycle(loop_state)
    run_results: list[dict[str, Any]] = []
    assisted_actions_log: list[dict[str, Any]] = []
    checker_decision: dict[str, Any] = {
        "verdict": "approved",
        "reason": "Checker approved target execution and assisted actions.",
    }
    attempts = (
        dict(loop_state.get("assisted_action_attempts") or {})
        if isinstance(loop_state, dict)
        else {}
    )
    state_updates: dict[str, Any] = {
        "assisted_action_attempts": attempts,
        "consecutive_checker_failures": int(
            loop_state.get("consecutive_checker_failures") or 0
        ),
        "paused": bool(loop_state.get("paused", False)),
        "pause_reason": loop_state.get("pause_reason"),
    }
    targets = planner_decision.selected_targets[: profile.max_iterations_per_cycle]

    for target in targets:
        target_context = _resolve_target_context(target)
        plan = policy_engine.plan_target(
            loop_state=loop_state,
            target=target,
            mode_name=target_context["mode_name"],
            run_dir=target_context["run_dir"],
            default_incomplete_run_action=incomplete_run_action,
            max_concurrency=target_context["max_concurrency"],
        )
        checker = verifier.verify_plan(plan, loop_state=loop_state, target=target)
        checker_decision = {
            "verdict": checker.verdict,
            "reason": checker.reason,
            "approved_actions": checker.approved_actions,
            "rejected_actions": checker.rejected_actions,
        }
        if not checker.approved and profile.readiness_level in {"L2", "L3"}:
            assisted_actions_log.extend(
                policy_engine.summarize_actions(
                    plan.assisted_actions, status="rejected"
                )
            )
            state_updates = _next_checker_failure_state(
                profile, loop_state, checker.reason, attempts
            )
            record_loop_cycle(
                profile,
                output_dir=output_dir,
                run_results=run_results,
                planner_decision=planner_decision.__dict__,
                reflection_decision={
                    "key_finding": "Checker rejected target execution before run.",
                    "ai_reflection": checker.reason,
                    "follow_up_enabled": True,
                    "escalation_items": [checker.reason],
                    "source": "checker",
                },
                checker_decision=checker_decision,
                assisted_actions=assisted_actions_log,
                state_updates=state_updates,
            )
            raise LoopProfileError(f"Checker rejected loop target: {checker.reason}")

        approved_actions = [
            action
            for action in plan.assisted_actions
            if action.action in checker.approved_actions
        ]
        assisted_actions_log.extend(
            policy_engine.summarize_actions(approved_actions, status="approved")
        )

        for action in approved_actions:
            key = policy_engine.retry_key(target, action.action)
            attempts[key] = int(attempts.get(key, 0)) + 1
            if (
                action.action == "regenerate_missing_summary"
                and target_context["run_dir"] is not None
            ):
                _regenerate_missing_summary(
                    target_context["run_dir"], mode_name=target_context["mode_name"]
                )

        effective_dry_run = (
            dry_run if target.get("dry_run") is None else bool(target.get("dry_run"))
        )
        summary = _execute_contract_run(
            contract_path=target["contract"],
            dry_run=effective_dry_run,
            persona_filter=target.get("persona"),
            scenario_filter=target.get("scenario"),
            adversarial_filter=target.get("adversarial_scenario"),
            max_concurrency_override=plan.max_concurrency_override,
            run_id_override=None,
            realtime_chat=realtime_chat,
            output_conversations=output_conversations,
            interactive_realtime_controls=None,
            incomplete_run_action=plan.incomplete_run_action,
        )
        status = (
            "completed_with_errors"
            if int(summary.get("errors") or 0) > 0
            else "completed"
        )
        run_results.append(
            {
                "timestamp": summary.get("completed_at")
                or summary.get("started_at")
                or summary.get("timestamp"),
                "mode": detect_mode_from_file(target["contract"]),
                "contract": target["contract"],
                "run_id": summary.get("run_id"),
                "status": status,
                "dry_run": effective_dry_run,
                "errors": int(summary.get("errors") or 0),
                "total_tokens": _extract_total_tokens(summary),
                "elapsed_seconds": summary.get("elapsed_seconds"),
                "output_dir": summary.get("output_dir"),
                "assisted_actions": [action.action for action in approved_actions],
                "checker_verdict": checker.verdict,
            }
        )

    reflection_decision = reasoner.reflect_on_cycle(
        loop_state, run_results, planner_decision
    )
    state_updates = _next_success_state(profile, loop_state, run_results, attempts)

    state = record_loop_cycle(
        profile,
        output_dir=output_dir,
        run_results=run_results,
        planner_decision=planner_decision.__dict__,
        reflection_decision=reflection_decision.__dict__,
        checker_decision=checker_decision,
        assisted_actions=assisted_actions_log,
        state_updates=state_updates,
    )
    return {
        "profile_id": profile.profile_id,
        "status": state.get("status"),
        "targets_executed": len(run_results),
        "planner": planner_decision.__dict__,
        "reflection": reflection_decision.__dict__,
        "run_results": run_results,
        "state_path": str(
            (output_dir / "loops" / "state" / f"{profile.profile_id}.json").resolve()
        ),
    }


def _resolve_target_context(target: dict[str, Any]) -> dict[str, Any]:
    contract_path = str(target.get("contract") or "")
    mode_name = detect_mode_from_file(contract_path)
    mode = get_mode(mode_name)
    contract = mode.load_contract(contract_path)
    run_dir = _resolve_run_dir(contract, mode_name=mode_name, run_id_override=None)
    max_concurrency = None
    if mode_name == "unified":
        max_concurrency = int(
            getattr(getattr(contract, "run", None), "max_concurrency", 0) or 0
        )
    return {
        "mode_name": mode_name,
        "run_dir": run_dir,
        "max_concurrency": max_concurrency,
    }


def _regenerate_missing_summary(run_dir: Path, *, mode_name: str) -> bool:
    if not run_dir.exists():
        return False
    summary_path = run_dir / "run_summary.json"
    if summary_path.exists():
        return False
    run_state_path = run_dir / "run_state.json"
    if not run_state_path.exists():
        return False

    try:
        state = json.loads(run_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    summary = state.get("summary")
    if not isinstance(summary, dict):
        metrics = state.get("metrics") or {}
        summary = {
            "run_id": state.get("run_id") or run_dir.name,
            "mode": mode_name,
            "status": state.get("status") or "unknown",
            "total_conversations": int(state.get("completed_conversations") or 0),
            "total_turns": int((metrics or {}).get("total_turns") or 0),
            "errors": int((metrics or {}).get("errors") or 0),
            "regenerated": True,
        }
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return True


def _extract_total_tokens(summary: dict[str, Any]) -> int:
    tokens = summary.get("tokens") or {}
    if not isinstance(tokens, dict):
        return 0
    total = 0
    for key in (
        "simulator_total_tokens",
        "chatbot_total_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
    ):
        total += int(tokens.get(key) or 0)
    return total


def _enforce_l3_preflight(
    profile: Any, loop_state: dict[str, Any], *, output_dir: Path
) -> None:
    if bool(loop_state.get("paused", False)) or bool(getattr(profile, "paused", False)):
        raise LoopProfileError(f"Loop profile is paused: {profile.profile_id}")

    if profile.readiness_level != "L3":
        return

    budget = dict(loop_state.get("budget") or {})
    daily_run_cap = loop_state.get("daily_run_cap")
    if daily_run_cap is not None and int(budget.get("spent_today_runs") or 0) >= int(
        daily_run_cap
    ):
        reason = f"Daily run cap reached: {daily_run_cap}"
        set_loop_paused(
            profile.profile_id,
            paused=True,
            reason=reason,
            output_dir=output_dir,
            profiles_dir=profile.source_path.parent,
        )
        raise LoopProfileError(reason)

    daily_token_cap = loop_state.get("daily_token_cap")
    if daily_token_cap is not None and int(
        budget.get("spent_today_tokens") or 0
    ) >= int(daily_token_cap):
        reason = f"Daily token cap reached: {daily_token_cap}"
        set_loop_paused(
            profile.profile_id,
            paused=True,
            reason=reason,
            output_dir=output_dir,
            profiles_dir=profile.source_path.parent,
        )
        raise LoopProfileError(reason)


def _next_checker_failure_state(
    profile: Any,
    loop_state: dict[str, Any],
    checker_reason: str,
    attempts: dict[str, Any],
) -> dict[str, Any]:
    failures = int(loop_state.get("consecutive_checker_failures") or 0) + 1
    updates = {
        "assisted_action_attempts": attempts,
        "consecutive_checker_failures": failures,
        "paused": bool(loop_state.get("paused", False)),
        "pause_reason": loop_state.get("pause_reason"),
    }
    threshold = int(
        profile.checker_policy.get("auto_pause_after_checker_failures", 3) or 3
    )
    if profile.readiness_level == "L3" and failures >= threshold:
        updates["paused"] = True
        updates["pause_reason"] = (
            f"Auto-paused after {failures} consecutive checker failures. Last reason: {checker_reason}"
        )
        updates["status"] = "paused"
    return updates


def _next_success_state(
    profile: Any,
    loop_state: dict[str, Any],
    run_results: list[dict[str, Any]],
    attempts: dict[str, Any],
) -> dict[str, Any]:
    spent_today_runs = int(
        ((loop_state.get("budget") or {}).get("spent_today_runs") or 0)
    ) + len(run_results)
    spent_today_tokens = int(
        ((loop_state.get("budget") or {}).get("spent_today_tokens") or 0)
    ) + sum(int(item.get("total_tokens") or 0) for item in run_results)
    updates = {
        "assisted_action_attempts": attempts,
        "consecutive_checker_failures": 0,
        "paused": False,
        "pause_reason": None,
    }
    if profile.readiness_level == "L3":
        daily_run_cap = loop_state.get("daily_run_cap")
        if daily_run_cap is not None and spent_today_runs >= int(daily_run_cap):
            updates["paused"] = True
            updates["pause_reason"] = (
                f"Auto-paused after reaching daily run cap: {daily_run_cap}"
            )
            updates["status"] = "paused"
        daily_token_cap = loop_state.get("daily_token_cap")
        if daily_token_cap is not None and spent_today_tokens >= int(daily_token_cap):
            updates["paused"] = True
            updates["pause_reason"] = (
                f"Auto-paused after reaching daily token cap: {daily_token_cap}"
            )
            updates["status"] = "paused"
    return updates


def _resolve_incomplete_action(
    configured: str, run_dir: Path, incomplete: dict[str, Any]
) -> str:
    if configured != "ask":
        return configured

    if not sys.stdin.isatty():
        raise ContractError(
            "Incomplete run detected in non-interactive mode at "
            f"{run_dir}. Use --incomplete-run-action resume|restart|abort."
        )

    completed = int(incomplete.get("completed_conversations") or 0)
    planned = int(incomplete.get("total_planned_conversations") or 0)
    print(
        "Detected an incomplete run at "
        f"{run_dir} (status={incomplete.get('status')}, completed={completed}/{planned or '?'})."
    )
    print(
        "Choose: [R]esume remaining conversations, [N]ew run (clean artifacts), or [A]bort"
    )

    while True:
        choice = input("Action [R/N/A]: ").strip().lower()
        if choice in {"r", "resume"}:
            return "resume"
        if choice in {"n", "new", "restart"}:
            return "restart"
        if choice in {"a", "abort"}:
            return "abort"
        print("Please enter R, N, or A.")


if __name__ == "__main__":
    entrypoint()
