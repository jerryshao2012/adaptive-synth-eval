# Dashboard Evaluation Launch and Re-evaluation Design

## Summary

Add a shared configuration dialog to the AI evaluation dashboard for starting, continuing, and re-evaluating post-hoc monitoring jobs. Dashboard launches are live-only and expose operational coverage controls without exposing metric prompts, thresholds, judge routing, custom metric files, or dry-run mode.

Completed runs gain a **Re-evaluate** action that rescans the source history under the selected sampling policy. Existing score batches whose input, metric, judge, and policy fingerprints remain valid are reused; only missing or stale batches invoke judges. This keeps unchanged re-evaluations fast while allowing changed sampling settings to add coverage.

## User Experience

- **Start**, **Continue**, and **Re-evaluate** open the same action-aware dialog rather than launching immediately.
- The dialog contains:
  - sampling strategy: `all`, `random`, or `systematic`;
  - sample size: positive integer, disabled with explanatory text when strategy is `all`;
  - interval minutes: positive integer;
  - max windows: optional positive integer, blank for unlimited.
- New runs default to `all`, sample size `1000`, interval `60`, and unlimited windows.
- Existing runs are prefilled from `monitoring_state.json`; legacy states without a saved max-window value use unlimited.
- The confirmation copy explains the action:
  - Start begins monitoring from the first source row.
  - Continue resumes from the saved cursor and permits updated settings for remaining windows.
  - Re-evaluate rescans from the first source row and reuses fingerprint-matching results.
- Completed runs show **Re-evaluate** whenever no launch is queued or in progress. Duplicate submissions remain disabled by a PID-backed launch lock and client-side pending state.
- Dashboard launches always use live model evaluation. The CLI retains its existing terminal-only `--dry-run` option.

## Architecture and Interfaces

### Dashboard contract

Extend the launch request to carry a discriminated action and all operational settings:

```ts
type MonitoringAction = "start" | "continue" | "reevaluate";

interface EvalRunParameters {
  samplingStrategy: "all" | "random" | "systematic";
  sampleSize: number;
  intervalMinutes: number;
  maxWindows: number | null;
}

interface MonitoringStartRequest extends EvalRunParameters {
  runId: string;
  action: MonitoringAction;
}
```

`RunSummary` gains `canReevaluate`, and the dashboard monitoring-status union gains `incomplete`. `MonitoringRunStatus.state` remains the source for the last saved settings, with typed normalization performed by a dashboard helper before values reach the form.

The monitoring API validates the action, enum values, positive integers, optional max windows, and run identifier. It launches `uv` with an executable plus argument array and `shell: false`; a human-readable command string may still be returned for diagnostics but is never executed. Run paths must resolve beneath `outputs/runs`.

### Monitoring CLI and runner

Add `ase monitor run --rescan`. The CLI passes `rescan: bool` to `run_monitoring`.

When rescan is requested, the runner:

1. Loads the existing state and score index normally.
2. Starts source traversal at line `0` and resets invocation progress counters.
3. Keeps existing score records in memory.
4. Applies the selected sampling policy to each window.
5. Reuses fresh score batches and evaluates only missing or stale batches using the existing fingerprint reconciliation logic.
6. Atomically writes the reconciled score set and final state through the existing writer paths.

Sampling policy is deliberately not added to evaluation fingerprints: sampling determines coverage, while evaluation fingerprints determine whether a stored score value is reusable. Existing records that are not selected during the new pass remain in `monitoring_scores.jsonl`.

Persist `max_windows` with the existing sample size, interval, and strategy in monitoring state so a later Continue or Re-evaluate dialog can reproduce the last launch settings. The Python artifact status remains `in_progress` when a max-window-limited invocation stops before the source cursor reaches the end; once its launch process is no longer active, the dashboard maps that state to `incomplete` and enables Continue.

## Data Flow and Failure Handling

1. The run header opens the dialog with normalized defaults from the selected run.
2. Client validation prevents invalid or duplicate submissions.
3. `POST /api/evaluations/monitoring` repeats validation at the trust boundary.
4. The server resolves the run directory, acquires the per-run launch lock, constructs safe CLI arguments, starts the detached process, and records the child PID in the lock.
5. Existing polling refreshes run summaries, monitoring state, progress, and score-backed dashboard views.

The launch lock is first written with a short queued-start expiry, then updated with the spawned `uv` PID. Polling treats the lock as active while that PID exists; a missing/dead PID or failed spawn removes the lock. The short expiry is only a fallback for the pre-spawn race or legacy locks, not the lifetime of a running job. This makes a slow live judge call remain `in_progress` without permitting a duplicate launch, while a crashed or max-window-limited process becomes `incomplete` and eligible for Continue after liveness is checked.

Action availability follows this table:

| Monitoring artifact | Active launch | Dashboard status | Enabled action |
| --- | --- | --- | --- |
| No state | No | `not_started` | Start |
| Any state | Yes, state not yet updated | `queued` | None |
| State `in_progress` | Yes | `in_progress` | None |
| State `in_progress` | No | `incomplete` | Continue |
| State `completed` | No | `completed` | Re-evaluate |

Invalid configuration or unsafe run identifiers return `400`; missing runs return `404`; conflicting active launches retain the existing non-duplicating response behavior. Spawn failures release the launch lock and return a server error. The dialog stays open with the returned message so the user can correct settings or retry. Re-evaluation never deletes monitoring scores or source artifacts.

## Testing and Acceptance Criteria

### Python monitoring tests

- `--rescan` on a completed, unchanged run traverses from row zero, preserves record identity/count, and performs no stale score refreshes.
- A rescan with broader systematic sampling evaluates previously unscored selected rows while retaining older records.
- A rescan with changed metric/input/judge fingerprints refreshes only stale batches.
- Max-window state is persisted and Continue resumes from the resulting cursor.
- Existing non-rescan resume and restart behavior remains unchanged.

### Dashboard tests

- Request validation accepts all supported strategies/actions and rejects invalid integers, unknown actions, unsafe run IDs, and dashboard dry-run input.
- CLI argument construction includes sampling strategy, size where applicable, interval, optional max windows, `resume`/`restart`, and `--rescan` only for Re-evaluate; it never enables `--dry-run`.
- Settings normalization uses new-run defaults and existing-state values correctly.
- PID-backed lock tests cover queued-before-spawn, live process, dead process cleanup, spawn failure cleanup, and legacy lock expiry.
- Action availability follows the lifecycle table: Start for untouched runs, Continue for inactive incomplete runs, and Re-evaluate for inactive completed runs, while queued/running launches remain disabled.
- Dialog submission sends the normalized configuration and presents server errors without closing.

Acceptance is complete when a user can configure and launch all three actions from the Monitor page, an unchanged completed run re-evaluates without judge calls, changed or missing score batches are refreshed, and the documented CLI behavior matches the dashboard behavior.

## Non-goals

- Editing metric definitions, prompts, thresholds, or judge/model routes.
- Selecting arbitrary custom metrics configuration paths.
- Choosing a provider or model in the dashboard.
- Dashboard dry-run mode.
- Deleting old scores to make a smaller sample replace historical coverage.
- Building a general-purpose job scheduler or persistent job-log service.
