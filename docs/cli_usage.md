# CLI Usage

Use `uv run ase` from the repository root, or install the project as a tool and use `ase` directly. This guide covers evaluation commands and runtime controls. See [Monitoring](monitoring.md), [Loop operations](loop_operations_runbook.md), and [Environment setup](environment_setup.md) for operational detail.

## Installation

Install the project and its dependencies:

```bash
uv sync
```

Run commands through the project environment:

```bash
uv run ase --help
```

To put `ase` on your `PATH`, optionally install it as an editable tool:

```bash
uv pip install -e .
uv tool install --editable .
ase --help
```

## Core workflow

### Validate a contract

```bash
uv run ase validate-contract contracts/examples/unified_evaluation_demo.yaml
```

Contract validation reports schema and configuration errors without starting an evaluation. See [Simulation contracts](contracts.md) for the synth and unified formats.

### Run an evaluation

```bash
uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --dry-run
```

`--dry-run` replaces live model and target calls with local mock behavior. Remove it only after configuring the required credentials and endpoints.

Useful options for both contract modes:

- `--output-conversations`: write a human-readable `conversations.txt` alongside the normal artifacts.
- `--realtime-chat`: stream persona and target messages to the terminal.
- `--persona <id>`: limit or filter the run to one persona.
- `--incomplete-run-action ask|resume|restart|abort`: choose how to handle an incomplete run directory.

The human-readable output includes conversation metadata, alternating persona and bot messages, and any turn errors. See [example_conversations_output.txt](example_conversations_output.txt) for a sample and [Output artifacts](output_artifacts.md) for the authoritative artifact reference.

### Unified-only options

These options require a unified contract. Supplying them to a synth contract produces a contract error:

- `--scenario <id>`: keep one synthetic scenario.
- `--adversarial-scenario <id>`: keep one adversarial scenario.
- `--max-concurrency <n>`: override the effective unified `run.max_concurrency` for this invocation.
- `--run-id <id>`: override the output run ID.

The current `ase run --help` text describes `--max-concurrency` using the legacy phrase `eval_plan max_concurrency`; the implementation applies it over `run.max_concurrency`.

### Summarize a completed run

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase summarize --run-id "$RUN_ID"
```

This prints `outputs/runs/<run_id>/run_summary.json`.

## Incomplete run recovery

When an existing run directory is incomplete, choose an action with `--incomplete-run-action`:

- `ask` (default): prompt for resume, restart, or abort.
- `resume`: continue the conversations not recorded as complete.
- `restart`: clear that run's existing artifacts and start again.
- `abort`: exit without running.

For a unified run, use the exact timestamped run-directory name under `outputs/runs/`. Without `--run-id`, recovery checks the contract's base ID instead of that generated directory. If the original invocation supplied a fixed `--run-id`, reuse that same value.

```bash
RUN_ID=copy_the_interrupted_run_id

uv run ase run \
  --contract contracts/examples/unified_evaluation_demo.yaml \
  --run-id "$RUN_ID" \
  --incomplete-run-action resume

uv run ase run \
  --contract contracts/examples/unified_evaluation_demo.yaml \
  --run-id "$RUN_ID" \
  --incomplete-run-action restart

uv run ase run \
  --contract contracts/examples/unified_evaluation_demo.yaml \
  --run-id "$RUN_ID" \
  --incomplete-run-action abort
```

Synth contracts do not accept `--run-id`; synth recovery resolves the run directory from the contract's output ID. In non-interactive environments, use `resume`, `restart`, or `abort` explicitly because `ask` requires a terminal. Checkpoint state is stored in `outputs/runs/<run_id>/run_state.json`.

Unified run-state schema v2 fingerprints the secret-safe effective contract and the exact ordered, filtered run plan. Resume rejects a changed contract or plan, restores actual token and component usage plus committed attack memory, and resets transient reservations. Legacy v1 checkpoints use best-effort recovery with a warning; unsupported future state versions are rejected. See [Output artifacts](output_artifacts.md) for the persisted schema.

## Real-time chat & interactive controls

Stream a run to the console:

```bash
uv run ase run \
  --contract contracts/examples/unified_evaluation_demo.yaml \
  --dry-run \
  --realtime-chat
```

Realtime output is additive: normal artifacts are still written. Unified mode can stream concurrent conversations. Supplying `--persona <id>` limits realtime execution to one conversation and effective concurrency of one.

Interactive controls are enabled by default with `--realtime-chat` for synth mode. Disable them when input is unavailable or automation owns the terminal:

```bash
uv run ase run \
  --contract contracts/examples/chatbot_test_contract.yaml \
  --realtime-chat \
  --no-interactive-realtime-controls
```

Available synth-mode controls are:

- `h` / `help`: show commands.
- `+` / `faster` and `-` / `slower`: adjust playback speed.
- `p` / `pause`: pause or resume turns.
- `q` / `stop`: stop the run early.
- `style <mode>`: set the active persona to `default`, `aggressive`, `polite`, `concise`, `confused`, or `anxious`.
- `l` / `list`: list active sessions in multi-persona runs.
- `s` / `switch <persona_id-conversation_id|conversation_id>`: change the focused session.

`--persona` disables `list` and `switch`. Persona style changes persist across session switches for the life of the run. Interactive mode requires `prompt_toolkit`, which is installed with the project.

## Monitoring command map

`monitor run` scores an existing run's `chat_history.jsonl`; it does not launch new evaluation conversations.

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase monitor run --run-folder "outputs/runs/$RUN_ID" --dry-run
```

Common flags are `--sample-size`, `--interval-minutes`, `--sampling-strategy`, `--max-windows`, `--metrics-config`, and `--incomplete-run-action`. See the [Monitoring guide](monitoring.md) for sampling, fingerprints, incremental scheduling, recovery, timestamps, and the complete flag reference.

## Loop command map

`loop` coordinates guarded recurring evaluation runs from profiles; it is separate from post-hoc monitoring.

```bash
PROFILE_ID=unified_regression_guard
uv run ase loop init --profile "$PROFILE_ID"
uv run ase loop run --profile "$PROFILE_ID"
uv run ase loop status --profile "$PROFILE_ID"
uv run ase loop audit --profile "$PROFILE_ID"
uv run ase loop pause --profile "$PROFILE_ID" --reason "maintenance"
uv run ase loop resume --profile "$PROFILE_ID"
uv run ase loop start --profile "$PROFILE_ID" --once
```

`loop start` also supports recurring operation for one profile or `--all`, while `loop status` and `loop audit` accept an omitted `--profile` to cover all profiles. Loop execution defaults to dry-run; `--no-dry-run` enables live target calls, and an explicit target-level `dry_run` value in the profile overrides the command default.

See [Loop engineering](loop_engineering_for_adversarial_adaptive_synthetic_evaluation.md) for readiness levels, profile schema, control guarantees, and artifacts. Use the [Loop operations runbook](loop_operations_runbook.md) for startup, kill-switch handling, audits, recovery, and guardrail tuning.

## Command help

The installed CLI is the final authority for available flags:

```bash
uv run ase --help
uv run ase run --help
uv run ase monitor run --help
uv run ase loop --help
```
