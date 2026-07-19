# ASE Evaluation Dashboard

This Next.js application is the local investigation and review interface for
Adaptive Synth Eval (ASE) run artifacts. It reads evaluation data directly from
the parent repository, can launch post-hoc monitoring for an existing run, and
stores human-review and golden-dataset records alongside ASE outputs.

The dashboard provides three views:

- **Monitor** — select a run, inspect monitoring progress and quality trends,
  group failures, and drill into source turn and trace records.
- **Review Queue** — filter monitored turns, compare AI scores with human
  decisions, and save individual or bulk review actions.
- **Golden Dataset** — collect approved reviews into versioned datasets and
  export them as JSONL or CSV.

The root page redirects to `/monitor`.

## Prerequisites and repository layout

Run the dashboard from its directory inside an ASE checkout:

```text
adaptive-synth-eval/
├── ai-eval-dashboard/   # run Yarn commands here
└── outputs/             # dashboard reads and writes here
```

You need Node.js 20.9.0 or newer (required by the installed Next.js 16.2.10),
Yarn 1.x (`package.json` declares Yarn 1.22.22), and an ASE environment installed
with `uv` if you want the dashboard to start monitoring.
Provider credentials are required only for live monitoring; deterministic
monitoring can be run separately with `ase monitor run --dry-run`. Dashboard
launches are live only and require provider configuration.

The server resolves the repository root as the parent of its current working
directory. Starting Next.js from another directory can therefore point it at the
wrong `outputs/` tree.

## Start the dashboard

From the repository root:

```bash
cd ai-eval-dashboard
yarn install
yarn dev
```

Open [http://localhost:3000](http://localhost:3000). A production build uses:

```bash
yarn build
yarn start
```

All scripts defined in `package.json` are:

| Command | Purpose |
| --- | --- |
| `yarn dev` | Start the webpack development server |
| `yarn dev:turbo` | Start the default Next.js development server |
| `yarn build` | Create a production build |
| `yarn start` | Serve a completed production build |
| `yarn lint` | Run ESLint |
| `yarn test` | Run the Vitest suite once |
| `yarn test:watch` | Run Vitest in watch mode |

## Generate dashboard data

The dashboard lists directories under `outputs/runs/`. A run needs
`chat_history.jsonl` before ASE monitoring can score it. Use the canonical
[monitoring guide](../docs/monitoring.md) to generate or refresh monitoring data;
it covers sampling, incremental runs, provider setup, recovery, and scheduling.

The Monitor page can Start a run that has not been monitored, Continue an
incomplete run, or Re-evaluate a completed run. Every action opens a dialog for
the sampling strategy, per-window sample size, interval minutes, and optional
maximum windows. Continue and Re-evaluate are prefilled from the saved
`monitoring_state.json` values.

Start uses the runner's restart recovery action, Continue resumes from its saved
cursor, and Re-evaluate resumes with `--rescan`. A rescan traverses the selected
source rows from the beginning but reuses fingerprint-matching metric results;
only missing or stale evaluation groups require model calls. The dashboard does
not offer dry-run scoring, custom metrics configuration, or arbitrary CLI
arguments. Use the [monitoring guide](../docs/monitoring.md) for those CLI-only
workflows.

Launches are detached and tracked as Queued before the child writes fresh state,
then In Progress. The dashboard prevents another launch for that run while the
tracked process remains active.

For complete field definitions and lifecycle details, see
[output artifacts](../docs/output_artifacts.md).

## Artifacts used by the dashboard

Run-scoped files live in `outputs/runs/<run_id>/`:

| Artifact | Dashboard use |
| --- | --- |
| `chat_history.jsonl` | Source conversations for monitoring and trace drill-down |
| `monitoring_scores.jsonl` | Charts, failures, review queue, and golden-dataset records |
| `monitoring_state.json` | Monitoring status, progress, and fingerprints |
| `eval_progress.md` | Human-readable monitoring progress |
| `monitoring.log` | Append-only stdout/stderr from dashboard-launched monitoring processes |
| `run_state.json` | Run metadata and artifact validation |
| `run_summary.json` | Run mode and completion metadata |
| `turns.jsonl` | Additional unified-turn detail in trace drill-down, when present |
| `human_reviews.jsonl` | Human review decisions written by the Review Queue |

Golden-dataset metadata is written to
`outputs/golden_datasets/<dataset_id>.json`. Exports are assembled on demand from
the dataset's current record references, monitoring records, and matching human
reviews. New datasets initially select approved reviews, but exporting does not
recheck approval status after the dataset metadata has been updated.

## Server and API behavior

All dashboard data access is implemented by Node.js server routes:

- `/api/evaluations/runs` enumerates run directories and derives status from run
  and monitoring artifacts.
- `/api/evaluations/history` reads `monitoring_scores.jsonl` for a supplied
  `runId`. Without a `runId`, it returns generated mock data unless
  `EVAL_BACKEND_URL` is set, in which case it proxies history requests to that
  backend.
- `/api/evaluations/monitoring` reads monitoring status or starts a detached
  local `ase monitor run` process. Validated single-segment run IDs and a
  PID-backed launch lock prevent unsafe paths and duplicate active launches. The
  process is spawned directly without a shell.
- `/api/evaluations/monitoring/log` returns at most the latest 256 KiB of the
  selected run's `monitoring.log`. The Monitor page polls it while a launch is
  Queued or In Progress and offers manual refresh after completion or interruption.
- `/api/evaluations/trace` joins a selected monitoring point to matching
  `monitoring_scores.jsonl`, `chat_history.jsonl`, and `turns.jsonl` records.
- `/api/evaluations/validation` checks the expected run and monitoring files and
  reports missing, empty, or malformed artifacts.
- `/api/review/*` builds the review queue from monitoring scores and persists
  review decisions to each run's `human_reviews.jsonl`.
- `/api/golden-dataset/*` creates and updates dataset metadata and exports
  the dataset's referenced records as JSONL or CSV.

### Local-only security boundary

This application is designed for a trusted local checkout, not direct exposure
to untrusted users or a public network. The monitoring launch and log routes
validate run identifiers and bind file access beneath `outputs/runs`, but other
server routes also accept run or dataset identifiers used in filesystem paths.
The application has no built-in authentication or authorization. Put an
authenticated, input-validating service boundary in front of it before any
shared or remote deployment.

The server can read evaluation content, write reviews and dataset metadata, and
start local processes with the dashboard user's permissions. Run it with the
least privileges needed and keep `outputs/` free of secrets that dashboard users
should not see.

## Troubleshooting

### No runs appear

- Confirm the server was started from `ai-eval-dashboard/`.
- Confirm run folders exist at `../outputs/runs/<run_id>/` relative to that
  directory.
- Refresh after an ASE run creates its run folder.

### A run has no charts or review rows

- Confirm `monitoring_scores.jsonl` exists and contains records with timestamps.
- Run or resume monitoring using the [monitoring guide](../docs/monitoring.md).
- Check `monitoring_state.json` and `eval_progress.md` for progress or recovery
  details.

### Start or Continue fails

- Run `uv run ase monitor run --help` at the repository root to verify ASE is
  installed.
- Confirm the selected run folder exists and contains `chat_history.jsonl`.
- Configure the provider environment required for live monitoring. For
  deterministic data, run the CLI separately with `--dry-run`; the dashboard
  intentionally has no dry-run control.
- Expand **Evaluation log** to inspect output from dashboard launches. The panel
  shows the latest 256 KiB. A CLI invocation started in another terminal appears
  there only when its stdout and stderr are redirected to the run's
  `monitoring.log`.

### Build, lint, or tests fail

Run `yarn install` inside `ai-eval-dashboard/`, then retry `yarn build`,
`yarn lint`, or `yarn test`. Use the error output to check whether your Node.js
version satisfies the installed Next.js release.

For framework-specific development details, see the
[Next.js documentation](https://nextjs.org/docs).
