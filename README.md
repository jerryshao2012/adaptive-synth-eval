# Adaptive Synthetic Eval

Python CLI for generating synthetic multi-turn ChatHistory data for an HR policy chatbot.

The active implementation is intentionally local-first:

- No production telemetry dependency
- No Azure AI Evaluation Simulator dependency
- No chatbot tool-call requirement
- Contract-driven personas, scenarios, traffic mix, synthetic days, and failure injection

## Quick Start

```bash
uv run adaptive-synth-eval validate-contract contracts/examples/one_week_chat_history.yaml
uv run adaptive-synth-eval run --contract contracts/examples/one_week_chat_history.yaml --dry-run
uv run adaptive-synth-eval summarize --run-id one_week_chat_history
```

Outputs are written under `outputs/runs/<run_id>/`.

## Main Artifacts

- `chat_history.jsonl`
- `chat_history.csv`
- `run_plan.json`
- `conversations.jsonl`
- `turns.jsonl`
- `scores.jsonl`
- `run_summary.json`
- `generation_report.md`

## Tests

```bash
uv run pytest -q
```
