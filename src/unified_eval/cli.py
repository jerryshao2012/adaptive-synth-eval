"""`eval` CLI — single entry point for the unified pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adaptive_synth_eval.config.contract import ContractError
from unified_eval.config.contract import load_unified_contract
from unified_eval.orchestrator.runner import run_unified


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate-contract":
            contract = load_unified_contract(args.contract)
            for w in contract.warnings:
                print(f"WARNING: {w}", file=sys.stderr)
            print("Contract valid")
            return 0

        if args.command == "run":
            contract = load_unified_contract(args.contract)
            summary = run_unified(
                contract,
                dry_run=args.dry_run,
                persona_filter=args.persona,
                scenario_filter=args.scenario,
                adversarial_filter=args.adversarial_scenario,
                max_concurrency_override=args.max_concurrency,
                run_id_override=args.run_id,
                realtime_chat=args.realtime_chat,
                output_conversations=args.output_conversations,
            )
            print(json.dumps(summary, indent=2, default=str))
            return 0

        if args.command == "summarize":
            summary_path = Path(args.output_dir) / "runs" / args.run_id / "run_summary.json"
            if not summary_path.exists():
                print(f"Run summary not found: {summary_path}", file=sys.stderr)
                return 2
            print(summary_path.read_text(encoding="utf-8"))
            return 0

        parser.print_help()
        return 1

    except ContractError as exc:
        print(f"ContractError: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-eval",
        description=(
            "Unified eval pipeline. Drives both synthetic conversations (ASE) and "
            "adversarial probes (ARE) from a single YAML contract."
        ),
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="{validate-contract,run,summarize}",
    )

    validate = sub.add_parser("validate-contract", help="Validate a unified contract file")
    validate.add_argument("contract", help="Path to a YAML/JSON unified contract")

    run = sub.add_parser("run", help="Run the unified eval from a contract")
    run.add_argument("--contract", required=True, help="Path to a YAML/JSON unified contract")
    run.add_argument("--dry-run", action="store_true",
                     help="Mock LLM + mock target chatbot (no API keys needed)")
    run.add_argument("--persona", help="Filter to a single persona_id")
    run.add_argument("--scenario", help="Filter to a single synth scenario_id")
    run.add_argument("--adversarial-scenario", help="Filter to a single adversarial scenario_id")
    run.add_argument("--max-concurrency", type=int, default=None,
                     help="Override eval_plan max_concurrency for this run")
    run.add_argument("--run-id", help="Override the run_id (defaults to contract.output.run_id or timestamp)")
    run.add_argument("--realtime-chat", action="store_true",
                     help="Stream persona and chatbot messages to console as turns happen. "
                          "Forces sequential execution (max_concurrency=1) for stable transcript ordering.")
    run.add_argument("--output-conversations", action="store_true",
                     help="Write conversations.txt in human-readable Persona/Bot format after the run.")

    summarize = sub.add_parser("summarize", help="Print run_summary.json for a previous run")
    summarize.add_argument("--run-id", required=True)
    summarize.add_argument("--output-dir", default="outputs",
                           help="Base output directory containing runs/<run_id>/ (default: outputs)")

    return parser


if __name__ == "__main__":
    entrypoint()
