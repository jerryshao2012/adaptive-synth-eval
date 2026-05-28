# Team Handoff

1. Install `uv`.
2. Clone or open this repository.
3. Validate an example contract.
4. Run the CLI in dry-run mode.
5. Review artifacts under `outputs/runs/<run_id>/`.

Recommended first command:

```bash
uv run ase run --contract contracts/examples/one_week_chat_history.yaml --dry-run
```

The package does not require production telemetry, Azure AI Evaluation Simulator, or chatbot tool-call support.
