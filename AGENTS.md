# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Common Commands

```bash
# Setup
cp src/.env.example src/.env   # Fill in API keys/endpoints, then:
uv sync                         # Install all deps
uv tool install --editable .    # Make `ase` globally available (optional)

# Validate a contract
uv run ase validate-contract contracts/examples/unified_evaluation_demo.yaml

# Run (dry-run = no real LLM calls)
uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --dry-run
uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --dry-run --realtime-chat

# Resume or restart an interrupted run (same run_id)
uv run ase run --contract <contract.yaml> --incomplete-run-action resume
uv run ase run --contract <contract.yaml> --incomplete-run-action restart

# Summarize a completed run
uv run ase summarize --run-id <run_id>

# Loop operations
uv run ase loop init --profile <profile_id>
uv run ase loop start --profile <profile_id>
uv run ase loop status --profile <profile_id>
uv run ase loop pause --profile <profile_id>
uv run ase loop resume --profile <profile_id>
uv run ase loop audit --profile <profile_id>

# Tests
uv run pytest                          # All tests
uv run pytest tests/unit/              # Unit tests only
uv run pytest tests/integration/       # Integration tests only
uv run pytest -k "test_name_pattern"   # Single test pattern
```

## Architecture

This is a contract-driven simulation engine for generating synthetic multi-turn HR chatbot conversations and performing adversarial red-teaming. The CLI entry point is `ase` (or `adaptive-synth-eval`), defined in `src/adaptive_synth_eval/cli.py`.

### Two Evaluation Modes

The system has two evaluation modes, dispatched through `evaluation/modes.py`:

1. **`synth`** — Legacy mode. Pure generation: persona-driven users chat with a target, with configurable traffic patterns and failure injection. Contract schema: `config/schemas.py` (`SimulationContract`). Runner: `engines/chat_history_simulation.py`.

2. **`unified`** — The primary mode going forward. Interleaves benign (synth) turns with adversarial red-teaming attacks within single conversations. Contract schema: `unified_eval/config/schemas.py` (`UnifiedContract`). Runner: `unified_eval/orchestrator/runner.py`.

Contracts auto-detect mode: a top-level `suite` key → unified; `simulation_suite` → synth. Environment variable placeholders (`${VAR}`) in contracts are resolved from `src/.env`.

### Unified Evaluation Pipeline (`unified_eval/`)

The orchestrator (`unified_eval/orchestrator/runner.py`) runs conversations concurrently. Each conversation:
1. A persona is selected and assigned a scenario (benign or adversarial based on a `coin_flip` ratio).
2. For benign turns, the synth persona LLM generates user messages; the target chatbot responds.
3. For adversarial turns, the `adversarial_response_engine/` takes over — an adversarial planner selects attack strategies, a generator crafts the attack message, and a safety judge scores the target's response.
4. Both turn types flow through the scoring engine (`unified_eval/scoring/`), which routes to appropriate scorers.
5. Output is written by `unified_eval/output/writer.py`.

### Adversarial Response Engine (`adversarial_response_engine/`)

The ARE is a self-contained red-teaming subsystem:
- `engine/attack_agent.py` — Main attack orchestrator using attack strategies from a shipped YAML catalog (`engine/*.yaml`).
- `engine/taxonomy.py` — Maps attack categories; `engine/selector.py` — Selects strategies based on conversation context.
- `engine/evaluator.py` + `engine/components.py` — Judge target responses for safety violations.
- `engine/reflection_engine.py` (implied) — Analyzes attack outcomes to adapt future strategies.
- `output/` — Real-time display, observability hooks, and attack memory storage.

### Loop Execution (`loop/`)

Continuous evaluation at L0-L3 readiness levels:
- **L0**: One-shot manual runs.
- **L1**: Assisted loops (business hours, human approval gates).
- **L2**: Semi-automated (extended hours, auto-recovery for known patterns).
- **L3**: Fully unattended (24/7, budget-capped, kill-switch guarded).

The loop subsystem (`loop/`) uses AI-driven discovery to find evaluation targets, a scheduler for recurring runs, a policy engine enforcing safety guardrails, a verifier checking outputs, and a persistent state store (`outputs/loops/`).

### Contract Formats

Two contract schemas exist side-by-side and share some parsed types (`Persona`, `Scenario`, `TargetChatbot`, `TimeWindow`):

- **Synth contracts**: Top-level keys `simulation_suite`, `target`, `time_window`, `persona_pool`, `scenario_catalog`, `traffic_orchestration`, `failure_injection`, `conversation_turns`, `output`.
- **Unified contracts**: Top-level keys `suite`, `llm`, `target`, `time_window`, `persona_pool`, `scenario_catalog`, `eval_plan`, `scoring`, `output`, `schedule`, `component_overrides`.

### LLM Client Architecture (`clients/`)

`clients/chatbot_factory.py` creates target chatbot clients. Supported backends: Azure OpenAI, AWS Bedrock, Ollama, OpenAI API, Anthropic. The factory inspects environment variables and contract config to determine the backend. `clients/chatbot.py` provides the base protocol.

### Testing Patterns

- Tests use `tmp_path` for isolated contract files, `monkeypatch` for mocking internal functions, and `capsys`/`caplog` for output capture.
- Integration tests (`tests/integration/test_cli_runs.py`) exercise the full CLI flow: validate → run (dry-run) → summarize.
- Unit tests use `dataclasses.replace()` to modify frozen contract dataclasses for test scenarios.
- `SimpleNamespace` is used as a lightweight mock for `EvaluationMode`.
- Many tests define contracts as inline JSON strings written to temp files rather than loading from `contracts/examples/`.

### Environment Variables

Configured via `src/.env` (copy from `src/.env.example`). Key variables include provider-specific API keys/endpoints, retry settings, proxy config, and base URLs for each LLM backend.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
