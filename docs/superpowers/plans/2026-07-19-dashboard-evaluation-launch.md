# Dashboard Evaluation Launch and Re-evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let dashboard users configure live monitoring launches, safely re-evaluate completed runs with fingerprint-aware reuse, and inspect the detached CLI's live output.

**Architecture:** Add an explicit `--rescan` traversal mode to the Python monitoring runner without changing score fingerprints. In the Next.js dashboard, separate pure launch configuration from server-only path/lock/process logic, launch `uv` without a shell into a run-scoped append log, and expose configuration and bounded log-tail components through the existing Monitor page.

**Tech Stack:** Python 3.11+, argparse, pytest, Next.js 16 App Router, React 19, TypeScript, TanStack Query, Vitest, Testing Library.

---

## File Map

- `src/adaptive_synth_eval/monitoring/runner.py`: rescan traversal and persisted operational settings.
- `src/adaptive_synth_eval/cli.py`: public `--rescan` flag.
- `ai-eval-dashboard/lib/monitoring-config.ts`: shared defaults, state normalization, request validation, and pure CLI argument construction.
- `ai-eval-dashboard/lib/server/run-paths.ts`: safe repository/run path resolution.
- `ai-eval-dashboard/lib/server/monitoring-launch.ts`: PID-backed launch transaction, detached process cleanup, and append-only log capture/tailing.
- `ai-eval-dashboard/lib/server/monitoring.ts`: artifact reads and lifecycle/status projection using launch liveness.
- `ai-eval-dashboard/components/dashboard/evaluation-config-dialog.tsx`: shared Start/Continue/Re-evaluate form.
- `ai-eval-dashboard/components/dashboard/evaluation-log-panel.tsx`: bounded live log presentation and bottom-aware scrolling.
- `ai-eval-dashboard/components/dashboard/run-selector-header.tsx` and Monitor page: action/dialog/log wiring.
- API routes and hooks: validated launch and bounded log-tail transport.

### Task 1: Add fingerprint-aware monitoring rescans

**Files:**
- Modify: `src/adaptive_synth_eval/cli.py`
- Modify: `src/adaptive_synth_eval/monitoring/runner.py`
- Modify: `tests/unit/test_monitoring_cli.py`
- Modify: `tests/integration/test_monitoring_versioning.py`

- [ ] **Step 1: Write failing CLI tests for unchanged reuse, expanded coverage, and persisted max windows**

Add tests with these assertions:

```python
def test_completed_rescan_reuses_unchanged_scores(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "rescan_same"
    _write_chat_history(run_dir, total_rows=4)
    args = _monitor_args(run_dir, sampling_strategy="systematic", sample_size=2)
    assert main(args) == 0
    before = _read_jsonl(run_dir / "monitoring_scores.jsonl")

    assert main([*args, "--rescan"]) == 0

    assert _read_jsonl(run_dir / "monitoring_scores.jsonl") == before
    state = json.loads((run_dir / "monitoring_state.json").read_text())
    assert state["status"] == "completed"
    assert state["next_line_index"] == 4
    assert state["evaluated_rows"] == 0


def test_rescan_with_broader_sampling_adds_only_missing_rows(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "rescan_coverage"
    _write_chat_history(run_dir, total_rows=10)
    assert main(_monitor_args(run_dir, sampling_strategy="systematic", sample_size=2)) == 0
    assert len(_read_jsonl(run_dir / "monitoring_scores.jsonl")) == 2

    broader = _monitor_args(run_dir, sampling_strategy="systematic", sample_size=4)
    assert main([*broader, "--rescan"]) == 0

    assert len(_read_jsonl(run_dir / "monitoring_scores.jsonl")) == 4
    state = json.loads((run_dir / "monitoring_state.json").read_text())
    assert state["evaluated_rows"] == 2


def test_max_windows_is_persisted_for_dashboard_defaults(tmp_path):
    run_dir = tmp_path / "outputs" / "runs" / "partial"
    _write_chat_history(run_dir, total_rows=5)
    assert main(_monitor_args(run_dir, interval_minutes=2, max_windows=1)) == 0
    state = json.loads((run_dir / "monitoring_state.json").read_text())
    assert state["max_windows"] == 1
```

Extend the versioning integration test by marking one judge batch stale before `--rescan` and asserting only that batch's version data changes.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
/opt/homebrew/bin/uv run pytest tests/unit/test_monitoring_cli.py tests/integration/test_monitoring_versioning.py -k "rescan or max_windows" -v
```

Expected: failures because argparse does not recognize `--rescan` and state omits `max_windows`.

- [ ] **Step 3: Implement the CLI and runner behavior**

Add the parser flag:

```python
monitor_run.add_argument(
    "--rescan",
    action="store_true",
    help="Rescan source history from the beginning while reusing fingerprint-valid scores.",
)
```

Pass `rescan=args.rescan` to `run_monitoring`. Add `rescan: bool = False` to the runner, persist `max_windows` through every `_build_state` call, and select traversal state with:

```python
reconciliation_needed = (
    rescan
    or not same_eval_fingerprint
    or not same_policy_fingerprints
    or source_relation in {"unknown", "rewritten"}
    or retryable_fallbacks
)
next_line_index = 0 if reconciliation_needed else int(state.get("next_line_index") or 0)
```

Do not clear `existing_scores`; existing `_stale_batch_ids_for_row` and `_refresh_existing_row` remain the only score-refresh authority. Include `max_windows` and `rescan` in the returned summary and show the saved max-window setting in `eval_progress.md`.

- [ ] **Step 4: Run Python monitoring tests**

Run:

```bash
/opt/homebrew/bin/uv run pytest tests/unit/test_monitoring_cli.py tests/integration/test_monitoring_versioning.py -v
```

Expected: all monitoring CLI/versioning tests pass.

- [ ] **Step 5: Commit the runner change**

```bash
git add src/adaptive_synth_eval/cli.py src/adaptive_synth_eval/monitoring/runner.py tests/unit/test_monitoring_cli.py tests/integration/test_monitoring_versioning.py
git commit -m "feat(monitoring): add reusable rescan mode"
```

### Task 2: Define and validate dashboard launch configuration

**Files:**
- Create: `ai-eval-dashboard/lib/monitoring-config.ts`
- Create: `ai-eval-dashboard/tests/unit/monitoring-config.test.ts`
- Create: `ai-eval-dashboard/tests/integration/monitoring-route.test.ts`
- Modify: `ai-eval-dashboard/types/evaluation.ts`
- Modify: `ai-eval-dashboard/app/api/evaluations/monitoring/route.ts`

- [ ] **Step 1: Write failing pure configuration tests**

Cover defaults, legacy/current state normalization, all three actions, each sampling strategy, nullable max windows, positive-integer validation, rejection of `dryRun`, unsafe IDs (`../escape`, `nested/run`, `nested\\run`, blank), and argument arrays. The core expected argument shape is:

```ts
expect(buildMonitoringArgs(request, "outputs/runs/run-1")).toEqual([
  "run", "ase", "monitor", "run",
  "--run-folder", "outputs/runs/run-1",
  "--sampling-strategy", "systematic",
  "--sample-size", "100",
  "--interval-minutes", "30",
  "--max-windows", "2",
  "--incomplete-run-action", "resume",
  "--rescan",
]);
expect(buildMonitoringArgs(request, "outputs/runs/run-1")).not.toContain("--dry-run");
```

- [ ] **Step 2: Run the new test and confirm module-not-found failure**

Run from `ai-eval-dashboard`:

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/unit/monitoring-config.test.ts
```

Expected: failure because `lib/monitoring-config.ts` does not exist.

- [ ] **Step 3: Add types and pure helpers**

Define:

```ts
export type MonitoringAction = "start" | "continue" | "reevaluate";
export type SamplingStrategy = "all" | "random" | "systematic";

export interface EvalRunParameters {
  samplingStrategy: SamplingStrategy;
  sampleSize: number;
  intervalMinutes: number;
  maxWindows: number | null;
}

export interface MonitoringStartRequest extends EvalRunParameters {
  runId: string;
  action: MonitoringAction;
}
```

Export `DEFAULT_MONITORING_PARAMETERS`, `normalizeMonitoringParameters(state)`, `parseMonitoringStartRequest(value)`, and `buildMonitoringArgs(request, relativeRunFolder)`. Parsing must reject unknown properties that attempt dashboard dry-run or custom metrics configuration, use integer checks rather than coercing partial strings, omit sample-size only when strategy is `all`, map Start to `restart`, map Continue/Re-evaluate to `resume`, and append `--rescan` only for Re-evaluate.

- [ ] **Step 4: Update the POST route to use parsed requests**

Replace ad hoc numeric checks with `parseMonitoringStartRequest`. Export an internal `handleMonitoringPost(request, startFn)` seam so route tests can inject a launcher without touching real run folders. Map malformed JSON and typed request/path validation errors to HTTP 400, then pass only the validated value to the launcher. Add route tests proving unsafe IDs and invalid operational fields return 400 rather than reaching `startFn`.

- [ ] **Step 5: Run tests and commit**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/unit/monitoring-config.test.ts tests/integration/monitoring-route.test.ts
git add ai-eval-dashboard/lib/monitoring-config.ts ai-eval-dashboard/types/evaluation.ts ai-eval-dashboard/app/api/evaluations/monitoring/route.ts ai-eval-dashboard/tests/unit/monitoring-config.test.ts ai-eval-dashboard/tests/integration/monitoring-route.test.ts
git commit -m "feat(dashboard): validate monitoring launch settings"
```

### Task 3: Make launch lifecycle PID-backed and capture CLI output

**Files:**
- Create: `ai-eval-dashboard/lib/server/run-paths.ts`
- Create: `ai-eval-dashboard/lib/server/monitoring-launch.ts`
- Create: `ai-eval-dashboard/tests/integration/monitoring-launch.test.ts`
- Modify: `ai-eval-dashboard/lib/server/monitoring.ts`
- Modify: `ai-eval-dashboard/app/api/evaluations/monitoring/route.ts`
- Modify: `ai-eval-dashboard/tests/integration/monitoring-route.test.ts`

- [ ] **Step 1: Write failing safe-path and launch-transaction tests**

Use a real temporary repository tree and injected process dependencies. Cover:

```ts
expect(() => resolveRunDirectory("../escape", tmpRepo)).toThrow();
expect(() => resolveRunDirectory("nested/run", tmpRepo)).toThrow();
expect(resolveRunDirectory("run 1", tmpRepo)).toBe(path.join(tmpRepo, "outputs/runs/run 1"));
```

The fake child must expose `pid`, `once`, `kill`, and `unref`. Assert:

- the initial lock is created exclusively;
- spawn receives executable `uv`, the pure argument array, `shell: false`, `detached: true`, and one append descriptor for both stdout/stderr;
- a timestamped launch boundary precedes child output;
- `unref` occurs only after atomic PID-lock promotion;
- live PID means active; dead PID removes the lock;
- spawn failure closes the descriptor and removes the lock;
- PID-persistence failure terminates/reaps the process group before lock removal;
- a stale legacy queued lock expires, while a live PID-backed lock does not use TTL.
- a syntactically valid missing run throws a typed `RunNotFoundError` before lock/log/spawn work.

- [ ] **Step 2: Run the integration test and confirm missing exports**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/integration/monitoring-launch.test.ts
```

Expected: module/export failures.

- [ ] **Step 3: Implement safe run paths and a dependency-injected launcher**

`resolveRunDirectory` must trim the ID, require one path segment, resolve beneath `<repo>/outputs/runs`, and never accept traversal. It throws a typed validation error for unsafe syntax and `RunNotFoundError` when the resolved directory does not exist. In `monitoring-launch.ts`, provide a production wrapper plus `createMonitoringLauncher(deps)` for deterministic tests. The ordered transaction is:

```ts
acquireQueuedLock();
const log = await fs.open(logPath, "a");
await log.write(launchBoundary);
const child = spawn("uv", args, { cwd: repoRoot, shell: false, detached: true,
  stdio: ["ignore", log.fd, log.fd] });
await waitForSpawnOrError(child);
await promoteLockAtomically({ launchId, pid: child.pid, ...metadata });
child.unref();
await log.close();
```

On promotion failure, send SIGTERM to the detached process group, wait up to five seconds, send SIGKILL if necessary, await close, then remove only the lock whose `launchId` matches. Close the parent descriptor in `finally`.

Update `handleMonitoringPost` to map `RunNotFoundError` to HTTP 404 while leaving unexpected launch failures as HTTP 500. Extend route tests to assert missing-run 404 and verify no lock, log, or spawn dependency was invoked.

- [ ] **Step 4: Project lifecycle status in `monitoring.ts`**

Replace TTL-only `isLaunchLockActive` with the launcher liveness result. Add `incomplete` to status types and use this precedence:

```ts
if (launch.active) return stateUpdatedAfterLaunch ? "in_progress" : "queued";
if (normalizedState === "completed") return "completed";
if (normalizedState === "in_progress") return "incomplete";
return hasScores ? "incomplete" : "not_started";
```

Set `canStart`, `canContinue`, and `canReevaluate` from that projected status, never from score-file existence alone.

- [ ] **Step 5: Run tests and commit**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/integration/monitoring-launch.test.ts tests/integration/monitoring-route.test.ts
git add ai-eval-dashboard/lib/server/run-paths.ts ai-eval-dashboard/lib/server/monitoring-launch.ts ai-eval-dashboard/lib/server/monitoring.ts ai-eval-dashboard/app/api/evaluations/monitoring/route.ts ai-eval-dashboard/tests/integration/monitoring-launch.test.ts ai-eval-dashboard/tests/integration/monitoring-route.test.ts
git commit -m "feat(dashboard): make monitoring launches observable"
```

### Task 4: Expose a bounded monitoring-log API

**Files:**
- Create: `ai-eval-dashboard/app/api/evaluations/monitoring/log/route.ts`
- Create: `ai-eval-dashboard/tests/integration/monitoring-log.test.ts`
- Modify: `ai-eval-dashboard/lib/server/monitoring-launch.ts`
- Modify: `ai-eval-dashboard/types/evaluation.ts`

- [ ] **Step 1: Write failing bounded-tail tests**

Use temporary files to cover missing log, exact/small content, content larger than 256 KiB, a start offset in the middle of a line, multibyte UTF-8 after the discarded newline, unsafe run ID, and missing run. Assert the response shape:

```ts
expect(result).toMatchObject({
  runId: "run-1",
  size: expect.any(Number),
  truncated: true,
  updatedAt: expect.any(String),
});
expect(Buffer.byteLength(result.content, "utf8")).toBeLessThanOrEqual(256 * 1024);
expect(result.content.startsWith("complete-line")).toBe(true);
```

- [ ] **Step 2: Run the test and confirm missing behavior**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/integration/monitoring-log.test.ts
```

- [ ] **Step 3: Implement `readMonitoringLogTail` and the GET route**

Read only the final 256 KiB. When truncated, discard bytes through the first newline so decoding begins on a complete line; return empty content if the tail contains no complete line. Return `{content: "", size: 0, truncated: false}` for a missing log, 404 for a missing run, and 400 for an invalid run ID.

- [ ] **Step 4: Run tests and commit**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/integration/monitoring-log.test.ts
git add ai-eval-dashboard/app/api/evaluations/monitoring/log/route.ts ai-eval-dashboard/lib/server/monitoring-launch.ts ai-eval-dashboard/types/evaluation.ts ai-eval-dashboard/tests/integration/monitoring-log.test.ts
git commit -m "feat(dashboard): expose monitoring log tail"
```

### Task 5: Build the shared evaluation configuration dialog

**Files:**
- Create: `ai-eval-dashboard/components/dashboard/evaluation-config-dialog.tsx`
- Create: `ai-eval-dashboard/tests/unit/evaluation-config-dialog.test.tsx`
- Modify: `ai-eval-dashboard/vitest.config.ts`
- Modify: `ai-eval-dashboard/package.json`
- Modify: `ai-eval-dashboard/package-lock.json`

- [ ] **Step 1: Install the existing-stack UI test dependencies**

From `ai-eval-dashboard`:

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm install --save-dev @testing-library/react @testing-library/user-event jsdom
```

Update Vitest include patterns to accept `tests/**/*.test.tsx`; individual component tests use `// @vitest-environment jsdom`.

- [ ] **Step 2: Write failing interaction tests**

Test action-specific title/copy, prefilled values, strategy selection, disabled sample size for `all`, positive-integer errors, nullable max windows, server error rendering, Cancel, and successful submission without closing until the async callback resolves.

- [ ] **Step 3: Run the test and confirm component-not-found failure**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/unit/evaluation-config-dialog.test.tsx
```

- [ ] **Step 4: Implement the dialog using existing UI primitives**

Use the repository's `Dialog`, `Button`, and native form controls. Keep form state local, reset from `initialValues` whenever a new action opens, validate before calling:

```ts
onSubmit({
  samplingStrategy,
  sampleSize,
  intervalMinutes,
  maxWindows: maxWindowsText === "" ? null : Number(maxWindowsText),
});
```

Do not add dry-run, model, metric, prompt, or custom-config controls.

- [ ] **Step 5: Run tests and commit**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/unit/evaluation-config-dialog.test.tsx
git add ai-eval-dashboard/components/dashboard/evaluation-config-dialog.tsx ai-eval-dashboard/tests/unit/evaluation-config-dialog.test.tsx ai-eval-dashboard/vitest.config.ts ai-eval-dashboard/package.json ai-eval-dashboard/package-lock.json
git commit -m "feat(dashboard): add evaluation configuration dialog"
```

### Task 6: Wire Start, Continue, and Re-evaluate into the Monitor page

**Files:**
- Modify: `ai-eval-dashboard/components/dashboard/run-selector-header.tsx`
- Modify: `ai-eval-dashboard/app/(dashboard)/monitor/page.tsx`
- Modify: `ai-eval-dashboard/hooks/use-evaluations.ts`
- Create: `ai-eval-dashboard/tests/unit/run-selector-header.test.tsx`

- [ ] **Step 1: Write failing action-availability tests**

Render the header for each lifecycle row and assert only Start, Continue, or Re-evaluate is shown as specified. Assert queued/in-progress states disable launches and clicking an action reports `{action, runId}` without immediately mutating.

- [ ] **Step 2: Run the focused test and confirm failure**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/unit/run-selector-header.test.tsx
```

- [ ] **Step 3: Replace immediate launches with dialog intent**

In the page, keep:

```ts
const [launchIntent, setLaunchIntent] = useState<{
  action: MonitoringAction;
  runId: string;
} | null>(null);
```

Open the shared dialog from all three header actions. Normalize initial values from the selected run's state, submit the typed request through `useStartMonitoring`, retain the dialog and error on failure, and close/refetch runs/status/evaluations after accepted launch. Use one pending launch key for duplicate suppression.

- [ ] **Step 4: Run tests and commit**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/unit/run-selector-header.test.tsx tests/unit/evaluation-config-dialog.test.tsx
git add 'ai-eval-dashboard/app/(dashboard)/monitor/page.tsx' ai-eval-dashboard/components/dashboard/run-selector-header.tsx ai-eval-dashboard/hooks/use-evaluations.ts ai-eval-dashboard/tests/unit/run-selector-header.test.tsx
git commit -m "feat(dashboard): configure evaluation actions"
```

### Task 7: Add the live Evaluation Log panel

**Files:**
- Create: `ai-eval-dashboard/components/dashboard/evaluation-log-panel.tsx`
- Create: `ai-eval-dashboard/tests/unit/evaluation-log-panel.test.tsx`
- Modify: `ai-eval-dashboard/hooks/use-evaluations.ts`
- Modify: `ai-eval-dashboard/app/(dashboard)/monitor/page.tsx`

- [ ] **Step 1: Write failing log-hook/panel tests**

Cover closed-panel no-fetch, fetch-on-open, two-second polling only for queued/in-progress status, manual refresh for completed/incomplete status, empty state, truncation notice, monospace output, and auto-scroll only when the viewport was already at the bottom.

- [ ] **Step 2: Run and confirm failure**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/unit/evaluation-log-panel.test.tsx
```

- [ ] **Step 3: Add the query hook and panel**

Add `useMonitoringLog(runId, open, active)` with `enabled: open && Boolean(runId)` and:

```ts
refetchInterval: open && active ? 2_000 : false
```

Render the panel directly below `RunSelectorHeader`. Reset open/scroll state when the selected run changes. Use a native scroll container ref for reliable `scrollTop`, `scrollHeight`, and `clientHeight` checks; do not continuously force-scroll users reading older output.

- [ ] **Step 4: Run tests and commit**

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test -- tests/unit/evaluation-log-panel.test.tsx
git add 'ai-eval-dashboard/app/(dashboard)/monitor/page.tsx' ai-eval-dashboard/components/dashboard/evaluation-log-panel.tsx ai-eval-dashboard/hooks/use-evaluations.ts ai-eval-dashboard/tests/unit/evaluation-log-panel.test.tsx
git commit -m "feat(dashboard): display live evaluation logs"
```

### Task 8: Document artifacts and verify end to end

**Files:**
- Modify: `docs/monitoring.md`
- Modify: `docs/output_artifacts.md`
- Modify: `ai-eval-dashboard/README.md`

- [ ] **Step 1: Update user and artifact documentation**

Document `--rescan`, persisted `max_windows`, dashboard live-only controls, Re-evaluate reuse semantics, `incomplete`/Continue behavior, `monitoring.log`, the 256 KiB UI tail, append history, and the fact that terminal-only CLI launches are not captured by the dashboard launcher log unless their output is separately redirected.

- [ ] **Step 2: Run Python verification**

```bash
/opt/homebrew/bin/uv run pytest tests/unit/test_monitoring_cli.py tests/integration/test_monitoring_versioning.py -v
/opt/homebrew/bin/uv run pytest tests/unit/ tests/integration/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Run dashboard verification**

From `ai-eval-dashboard`:

```bash
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm test
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm run lint
PATH=/opt/homebrew/bin:/usr/bin:/bin /opt/homebrew/bin/npm run build
```

Expected: Vitest, ESLint, and Next production build all pass.

- [ ] **Step 4: Run a local dry CLI smoke test and graph refresh**

Use a temporary run fixture or an existing non-production test run:

```bash
/opt/homebrew/bin/uv run ase monitor run --run-folder <test-run-folder> --dry-run --rescan --max-windows 1 --incomplete-run-action resume
/Users/jerryshao/.local/share/uv/tools/graphifyy/bin/graphify update .
```

Confirm the second unchanged rescan reports zero newly evaluated rows, then verify `git status` contains only intended source, test, documentation, lockfile, and refreshed graph artifacts.

- [ ] **Step 5: Commit documentation and graph update**

```bash
git add docs/monitoring.md docs/output_artifacts.md ai-eval-dashboard/README.md graphify-out/
git commit -m "docs: document dashboard evaluation relaunch"
```

- [ ] **Step 6: Final review**

Review the full diff against `docs/superpowers/specs/2026-07-18-dashboard-evaluation-launch-design.md`, confirm no dashboard path accepts dry-run/custom metric input, and confirm no shell-based process launch remains.
