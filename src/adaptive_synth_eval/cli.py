from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adaptive_synth_eval.clients.logger_utils import setup_logger
from adaptive_synth_eval.config.contract import ContractError, load_contract
from adaptive_synth_eval.engines.chat_history_simulation import run_simulation

logger = setup_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-contract":
            contract = load_contract(args.contract)
            for warning in contract.warnings:
                logger.warning(warning)
            logger.info("Contract valid")
            print("Contract valid")
            return 0
        if args.command == "run":
            contract = load_contract(args.contract)
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
            )
            logger.info("Run complete: %s", summary['run_id'])
            logger.info(json.dumps(summary, indent=2))
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
        prog="adaptive-synth-eval",
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
        help="Run a synthetic chat simulation from a contract",
        description="Execute a simulation run from a contract and write artifacts to outputs/runs/<run_id>/.",
    )
    run.add_argument("--contract", required=True, help="Path to a YAML/JSON simulation contract file")
    run.add_argument("--dry-run", action="store_true", help="Skip real chatbot calls and use mock responses")
    run.add_argument("--output-conversations", action="store_true",
                     help="Output conversations in human-readable format with Persona/Bot labels")
    run.add_argument(
        "--realtime-chat",
        action="store_true",
        help="Stream persona and chatbot messages to console in real time (supports multiple personas and switching)",
    )
    run.add_argument(
        "--interactive-realtime-controls",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable runtime controls during --realtime-chat (default: enabled with --realtime-chat). "
            "Use --no-interactive-realtime-controls to disable."
        ),
    )
    run.add_argument(
        "--persona",
        help="Limit/filter the simulation run to only a specific persona ID, disabling persona switching controls.",
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


if __name__ == "__main__":
    entrypoint()
