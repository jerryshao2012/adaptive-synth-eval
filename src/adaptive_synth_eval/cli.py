from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from adaptive_synth_eval.artifacts.run_state import clear_run_directory, detect_incomplete_run
from adaptive_synth_eval.clients.logger_utils import setup_logger
from adaptive_synth_eval.config.contract import ContractError
from adaptive_synth_eval.engines.chat_history_simulation import run_simulation
from adaptive_synth_eval.evaluation.modes import get_mode

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
    return (
        "source=adaptive_synth_eval.unified_eval.providers.llm_factory.build_component_llms"
    )


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
        )
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
            raise ContractError("Contract contains both synth and unified top-level structures.")
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
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
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
            mode_name = detect_mode_from_file(args.contract)
            mode = get_mode(mode_name)
            contract = mode.load_contract(args.contract)
            _log_run_configuration(
                contract,
                mode_name=mode_name,
                contract_path=args.contract,
                dry_run=args.dry_run,
                persona_filter=args.persona,
                scenario_filter=getattr(args, "scenario", None),
                adversarial_filter=getattr(args, "adversarial_scenario", None),
                max_concurrency_override=getattr(args, "max_concurrency", None),
                realtime_chat=args.realtime_chat,
            )

            run_dir = _resolve_run_dir(contract, mode_name=mode_name, run_id_override=getattr(args, "run_id", None))
            resume_incomplete = False
            if run_dir is not None:
                incomplete = detect_incomplete_run(run_dir)
                if incomplete is not None:
                    action = _resolve_incomplete_action(args.incomplete_run_action, run_dir, incomplete)
                    if action == "abort":
                        raise ContractError(
                            "Detected an incomplete prior run. Re-run with "
                            "--incomplete-run-action resume or --incomplete-run-action restart."
                        )
                    if action == "restart":
                        logger.warning("Cleaning existing run artifacts before starting a new run: %s", run_dir)
                        clear_run_directory(run_dir)
                    elif action == "resume":
                        logger.warning("Resuming incomplete run from existing artifacts: %s", run_dir)
                        resume_incomplete = True

            if mode_name == "synth":
                # Check unified-only flags
                unified_flags = []
                if getattr(args, "scenario", None) is not None:
                    unified_flags.append("--scenario")
                if getattr(args, "adversarial_scenario", None) is not None:
                    unified_flags.append("--adversarial-scenario")
                if getattr(args, "max_concurrency", None) is not None:
                    unified_flags.append("--max-concurrency")
                if getattr(args, "run_id", None) is not None:
                    unified_flags.append("--run-id")
                if unified_flags:
                    raise ContractError(
                        f"Unified-only flags {', '.join(unified_flags)} cannot be used with a synth-only contract.")

                interactive_controls = args.interactive_realtime_controls
                if interactive_controls is None:
                    interactive_controls = args.realtime_chat
                summary = run_simulation(
                    contract,
                    dry_run=args.dry_run,
                    output_conversations=args.output_conversations,
                    realtime_chat=args.realtime_chat,
                    interactive_realtime_controls=interactive_controls,
                    persona_filter=args.persona,
                    resume_incomplete=resume_incomplete,
                )
            else:
                interactive_controls = args.interactive_realtime_controls
                if interactive_controls is None:
                    interactive_controls = args.realtime_chat
                summary = mode.run(
                    contract,
                    dry_run=args.dry_run,
                    persona_filter=args.persona,
                    scenario_filter=args.scenario,
                    adversarial_filter=args.adversarial_scenario,
                    max_concurrency_override=args.max_concurrency,
                    run_id_override=args.run_id,
                    realtime_chat=args.realtime_chat,
                    output_conversations=args.output_conversations,
                    interactive_realtime_controls=interactive_controls,
                    resume_incomplete=resume_incomplete,
                )

            logger.info("Run complete: %s", summary['run_id'])
            logger.info(json.dumps(summary, indent=2, default=str))
            print(f"Run complete: {summary['run_id']}")
            return 0

        if args.command == "summarize":
            summary_path = Path(args.output_dir) / "runs" / args.run_id / "run_summary.json"
            if not summary_path.exists():
                logger.error("Run summary not found: %s", summary_path)
                return 2
            print(summary_path.read_text(encoding="utf-8"))
            return 0

        parser.print_help()
        return 1
    except ContractError as exc:
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
            "Use subcommands to validate a contract, run a simulation, or summarize a prior run."
        ),
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        description="Available operations",
        metavar="{validate-contract,run,summarize}",
    )
    validate = sub.add_parser(
        "validate-contract",
        help="Validate a simulation contract file and report schema or config issues",
        description="Validate a simulation contract file and print warnings if present.",
    )
    validate.add_argument("contract", help="Path to a YAML/JSON simulation contract file")

    run = sub.add_parser(
        "run",
        help="Run a synthetic or unified chat simulation from a contract",
        description="Execute a simulation run from a contract and write artifacts to outputs/runs/<run_id>/.",
    )
    run.add_argument("--contract", required=True, help="Path to a YAML/JSON simulation contract file")
    run.add_argument("--dry-run", action="store_true", help="Skip real chatbot calls and use mock responses")
    run.add_argument("--output-conversations", action="store_true",
                     help="Output conversations in human-readable format with Persona/Bot labels")
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
    return parser


def _resolve_run_dir(contract: Any, *, mode_name: str, run_id_override: str | None) -> Path | None:
    output = getattr(contract, "output", None)
    if output is None:
        return None

    base_dir = getattr(output, "base_dir", None)
    if base_dir is None:
        return None

    run_id = run_id_override if mode_name == "unified" and run_id_override else getattr(output, "run_id", None)
    if not run_id:
        return None
    return Path(base_dir) / "runs" / run_id


def _resolve_incomplete_action(configured: str, run_dir: Path, incomplete: dict[str, Any]) -> str:
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
    print("Choose: [R]esume remaining conversations, [N]ew run (clean artifacts), or [A]bort")

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
