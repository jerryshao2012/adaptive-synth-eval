from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adaptive_synth_eval.config.contract import ContractError, load_contract
from adaptive_synth_eval.engines.chat_history_simulation import run_simulation


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-contract":
            contract = load_contract(args.contract)
            for warning in contract.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
            print("Contract valid")
            return 0
        if args.command == "run":
            contract = load_contract(args.contract)
            summary = run_simulation(contract, dry_run=args.dry_run)
            print(f"Run complete: {summary['run_id']}")
            print(json.dumps(summary, indent=2))
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
        print(str(exc), file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adaptive-synth-eval")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-contract")
    validate.add_argument("contract")
    run = sub.add_parser("run")
    run.add_argument("--contract", required=True)
    run.add_argument("--dry-run", action="store_true")
    summarize = sub.add_parser("summarize")
    summarize.add_argument("--run-id", required=True)
    summarize.add_argument("--output-dir", default="outputs")
    return parser


if __name__ == "__main__":
    entrypoint()
