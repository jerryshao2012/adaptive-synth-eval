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
monitoring can be run separately with `ase monitor run --dry-run`.

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

The Monitor page can also start or continue monitoring. Its server route launches
this repository's CLI from the repository root with `uv run ase monitor run`, a
sample size, an interval, and either `restart` or `resume`. Launching is detached,
so the page polls state files rather than streaming command output.

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
  local `ase monitor run` process. A short-lived lock prevents duplicate launches.
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
to untrusted users or a public network. Several server routes accept run or
dataset identifiers that are used in filesystem paths, and the monitoring route
builds a shell command from request data. Only the validation route currently
applies an explicit path-traversal check; the application also has no built-in
authentication or authorization. Put an authenticated, input-validating service
boundary in front of it before any shared or remote deployment.

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
- Configure the provider environment required for live monitoring, or first
  generate deterministic data from the CLI with `--dry-run`.

### Build, lint, or tests fail

Run `yarn install` inside `ai-eval-dashboard/`, then retry `yarn build`,
`yarn lint`, or `yarn test`. Use the error output to check whether your Node.js
version satisfies the installed Next.js release.

For framework-specific development details, see the
[Next.js documentation](https://nextjs.org/docs).
