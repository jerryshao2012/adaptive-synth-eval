# Monitoring Existing Runs

Monitoring scores conversations that ASE has already produced. It reads `outputs/runs/<run_id>/chat_history.jsonl`, evaluates selected rows, and atomically writes dashboard-oriented records to `monitoring_scores.jsonl` in the same run directory.

This is distinct from loop orchestration:

- `ase monitor run` performs post-hoc scoring of existing chat history. It does not create conversations or invoke the configured target.
- `ase loop` schedules and safeguards recurring evaluation runs from loop profiles. Start with the [Loop operations runbook](loop_operations_runbook.md) when the goal is to generate new runs repeatedly.
- `ase metrics serve` exposes the same packaged evaluator definitions for stateless payload scoring without reading or writing run artifacts. See the [Standalone metrics API](metrics_api.md).

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

The effective sampling strategy, sample size, interval, and `max_windows` value
are saved in `monitoring_state.json`. The dashboard uses those persisted values
to prefill a later Continue or Re-evaluate dialog. A blank dashboard Max windows
field is stored as `null` and means unlimited.

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

Use `--rescan` to traverse the source history again from row zero without
discarding existing scores:

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase monitor run \
  --run-folder "outputs/runs/$RUN_ID" \
  --sampling-strategy systematic \
  --sample-size 100 \
  --incomplete-run-action resume \
  --rescan
```

The rescan reconciles each selected row and metric group against its stored
value fingerprints: metric content, evaluator input, and judge identity.
Matching numeric results are reused without an evaluation-model call; only
missing groups, groups with stale value fingerprints, and retryable-fallback
groups are evaluated again. Policy fingerprints are separate: a threshold-only
change reuses the numeric score and recalculates its pass/warn/fail label without
calling the judge. A completed unchanged run can therefore finish with
`evaluated_rows: 0`. Changing the sampling settings can select additional rows,
while valid scores for rows already evaluated remain reusable.

## Dashboard launches and lifecycle

The Monitor page exposes one configured action for the selected run:

- **Start** appears when monitoring has not started. It launches with
  `--incomplete-run-action restart`.
- **Continue** appears when a saved monitoring state is incomplete and there is
  no active launch. It launches with `--incomplete-run-action resume` and uses
  the saved cursor when evaluation/policy fingerprints and source identity still
  match. Changed fingerprints, unknown or rewritten source history, or a
  retryable fallback trigger reconciliation from row zero instead.
- **Re-evaluate** appears after monitoring completes. It launches with
  `--incomplete-run-action resume --rescan`, so the runner checks all selected
  source rows while retaining fingerprint-valid results.
- A launch is reported as **Queued** until the new process has produced newer
  in-progress state, then as **In Progress**. Launch actions are unavailable in
  both states.

Each action opens the same configuration dialog for sampling strategy, sample
size, interval minutes, and optional maximum windows. The sample-size control is
not used with the `all` strategy. Continue and Re-evaluate are prefilled from
`monitoring_state.json`; invalid or legacy values fall back to CLI defaults.

Dashboard launches are always live evaluation-model runs. The dashboard does
not expose or accept `--dry-run`, `--metrics-config`, or other custom CLI
arguments. Use the CLI directly when deterministic dry-run scoring or a custom
metrics file is required.

### Dashboard evaluation log

For each accepted dashboard launch, the server appends a timestamped launch
boundary and the detached CLI's stdout and stderr to
`outputs/runs/<run_id>/monitoring.log`. Re-evaluation and subsequent launches
append to the same file rather than replacing earlier output.

Expand **Evaluation log** on the Monitor page to inspect it. While the panel
remains expanded and a launch is Queued or In Progress, it polls for new
content. Once the run is Complete or Incomplete, use its Refresh button. The API
and UI expose at most the latest 256 KiB and omit a partial first line when the
file is larger.

Only processes launched by the dashboard are automatically connected to this
file. Output from `ase monitor run` started in another terminal is not captured
unless that command is explicitly redirected to the same path, for example:

```bash
RUN_ID=copy_the_run_id_printed_by_ase_run
uv run ase monitor run \
  --run-folder "outputs/runs/$RUN_ID" \
  --incomplete-run-action resume \
  >> "outputs/runs/$RUN_ID/monitoring.log" 2>&1
```

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
                [--rescan]
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
| `--rescan` | Traverse source history from the beginning and reuse fingerprint-valid stored scores |
| `--metrics-config` | Optional path to a custom monolithic metrics YAML file |
| `--dry-run` | Use deterministic local scoring instead of live evaluation-model calls |
| `--incomplete-run-action` | Ask, resume, restart, or abort when monitoring state is incomplete |

Run `uv run ase monitor run --help` to confirm the options for the installed revision.
