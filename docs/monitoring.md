# Monitoring Existing Runs

Monitoring scores conversations that ASE has already produced. It reads `outputs/runs/<run_id>/chat_history.jsonl`, evaluates selected rows, and atomically writes dashboard-oriented records to `monitoring_scores.jsonl` in the same run directory.

This is distinct from loop orchestration:

- `ase monitor run` performs post-hoc scoring of existing chat history. It does not create conversations or invoke the configured target.
- `ase loop` schedules and safeguards recurring evaluation runs from loop profiles. Start with the [Loop operations runbook](loop_operations_runbook.md) when the goal is to generate new runs repeatedly.

See [Output artifacts](output_artifacts.md) for the monitoring record and state schemas, and [Dashboard setup](../ai-eval-dashboard/README.md) to view the results.

## Quick start

Use deterministic local scores to verify a run folder without making evaluation-model calls:

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase monitor run \
  --run-folder "outputs/runs/$RUN_ID" \
  --dry-run
```

For live model evaluation, configure a supported model provider and omit `--dry-run`:

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase monitor run \
  --run-folder "outputs/runs/$RUN_ID" \
  --sampling-strategy random \
  --sample-size 500
```

The run folder must already contain `chat_history.jsonl`. Provider configuration is covered in [Environment setup](environment_setup.md).

## Sampling and windows

The runner reads the full chat history in sequential time windows. `--interval-minutes` controls the width of each window, and `--sample-size` is a per-window limit rather than a total-run limit.

| Option | Default | Behavior |
| --- | --- | --- |
| `--sample-size` | `1000` | Maximum selected rows per window for `random` or `systematic` sampling |
| `--interval-minutes` | `60` | Time-window width in minutes |
| `--sampling-strategy` | `all` | `all`, `random`, or `systematic` |
| `--max-windows` | unlimited | Stop after this many windows in the current invocation |

With `--sampling-strategy all`, every row in the window is evaluated, so `--sample-size` does not limit it. Use `random` for a random subset or `systematic` for an evenly spaced subset.

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase monitor run \
  --run-folder "outputs/runs/$RUN_ID" \
  --sampling-strategy systematic \
  --sample-size 100 \
  --max-windows 1
```

Rows not selected in a sampled window are recorded as skipped as the runner advances. Use a deliberate sampling policy when coverage requirements matter.

## Incremental and scheduled monitoring

Progress is stored in `monitoring_state.json`. When the evaluation and policy fingerprints are unchanged, a later invocation resumes from `next_line_index`; if new rows were appended to `chat_history.jsonl`, only the appended range needs processing. When there are no new rows, the command completes without scoring calls.

Use the same idempotent command from cron, systemd, or another scheduler:

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase monitor run \
  --run-folder "outputs/runs/$RUN_ID" \
  --sampling-strategy systematic \
  --sample-size 1000 \
  --interval-minutes 30 \
  --incomplete-run-action resume
```

Example cron entry, every 15 minutes. Replace `copy_the_run_id_printed_by_ase_run` with the exact run ID printed by `ase run`:

```cron
*/15 * * * * cd /path/to/adaptive-synth-eval && uv run ase monitor run --run-folder outputs/runs/copy_the_run_id_printed_by_ase_run --sampling-strategy systematic --sample-size 1000 --interval-minutes 30 --incomplete-run-action resume >> /tmp/ase-monitor.log 2>&1
```

Choose cadence based on traffic freshness and evaluation-model cost. Scheduling monitoring does not schedule new ASE runs; use `ase loop start` for that workflow.

## Automatic versioning and re-evaluation

Monitoring uses SHA-256-derived fingerprints to decide whether stored scores remain reusable:

- A per-metric content fingerprint covers the metric key, normalized prompt template, evaluation output key, score-inversion setting, and heuristic rules.
- The composite evaluation fingerprint combines every metric content fingerprint with the resolved model provider and model/deployment identity. A changed metric definition or model causes affected score groups to be refreshed.
- A per-metric policy fingerprint covers `warn_below` and `fail_below`. A threshold-only change recalculates pass/warn/fail labels from stored numeric scores without an LLM call.

These fingerprints are generated automatically; there is no metric-version flag. Metric definitions are shipped in `src/adaptive_synth_eval/monitoring/metrics/*.yaml`. A custom monolithic metrics file can be supplied with `--metrics-config` for testing or controlled overrides.

## Recovery behavior

If `monitoring_state.json` says a run is incomplete, `--incomplete-run-action` controls the next invocation:

- `ask` (default): prompt for an action in an interactive terminal.
- `resume`: continue from persisted state when fingerprints still match.
- `restart`: remove monitoring state and process from the beginning; existing score records are reconciled by conversation and turn identity.
- `abort`: exit without continuing.

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase monitor run \
  --run-folder "outputs/runs/$RUN_ID" \
  --incomplete-run-action resume
```

Changes to evaluation or policy fingerprints trigger reconciliation from the start so stale records can be refreshed or reclassified. Score-file writes and state-file writes use temporary files plus atomic replacement.

## Timestamps and provenance

Each monitoring score uses the source chat row's original time as its primary `timestamp`. Dashboard date filters and charts therefore follow when the conversation occurred, not when monitoring ran. Evaluation time is retained separately in `value_versions.generated_at`, together with model identity and content/policy fingerprints.

If a source row lacks a usable timestamp, the runner derives a deterministic fallback for windowing and output ordering. See [Output artifacts](output_artifacts.md) for the complete field definitions.

## Flag reference

```text
ase monitor run --run-folder RUN_FOLDER
                [--sample-size SAMPLE_SIZE]
                [--interval-minutes INTERVAL_MINUTES]
                [--sampling-strategy {all,random,systematic}]
                [--max-windows MAX_WINDOWS]
                [--metrics-config METRICS_CONFIG]
                [--dry-run]
                [--incomplete-run-action {ask,resume,restart,abort}]
```

| Flag | Meaning |
| --- | --- |
| `--run-folder` | Existing `outputs/runs/<run_id>` directory containing `chat_history.jsonl` |
| `--sample-size` | Rows selected per time window; must be greater than zero |
| `--interval-minutes` | Time-window width; must be greater than zero |
| `--sampling-strategy` | Select all rows, a random subset, or an evenly spaced subset |
| `--max-windows` | Optional cap on windows processed in this invocation |
| `--metrics-config` | Optional path to a custom monolithic metrics YAML file |
| `--dry-run` | Use deterministic local scoring instead of live evaluation-model calls |
| `--incomplete-run-action` | Ask, resume, restart, or abort when monitoring state is incomplete |

Run `uv run ase monitor run --help` to confirm the options for the installed revision.
