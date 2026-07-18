# Loop Operations Runbook

Use this runbook to initialize, inspect, start, pause, audit, and recover continuous evaluation loops. For readiness levels, module boundaries, profile fields, and artifact semantics, see [Loop engineering](loop_engineering_for_adversarial_adaptive_synthetic_evaluation.md).

Examples use `uv run ase`. If `ase` is installed as a tool, omit `uv run`.

## Preconditions

Before allowing a recurring or live loop:

1. Configure provider credentials and target connectivity as described in [Environment setup](environment_setup.md).
2. Validate every contract referenced by the profile with `uv run ase validate-contract <contract-path>`.
3. Review the profile's readiness level, targets, cadence, and checker policy.
4. For L3, require an active window, at least one daily cap, and `checker_policy.auto_pause_after_checker_failures` of at least `1`.
5. Keep the first cycle in dry-run mode. `loop run` and `loop start` default to dry-run, but a target-level `dry_run` value overrides that command default; confirm no target sets `dry_run: false` before validation.

Checked-in profiles are in `loops/profiles/`:

```bash
find loops/profiles -maxdepth 1 -type f -print | sort
```

## Initialize and inspect

Initialize persistent assets for one profile:

```bash
PROFILE_ID=unified_regression_guard
uv run ase loop init --profile "$PROFILE_ID"
```

Inspect its persisted state and readiness report:

```bash
uv run ase loop status --profile "$PROFILE_ID"
uv run ase loop audit --profile "$PROFILE_ID"
```

Omit `--profile` to inspect or audit all profiles. Use `--profiles-dir` and `--output-dir` only when operating outside the default `loops/profiles` and `outputs` paths.

## Validate one cycle

Dry-run limits live model and target calls; it is not an artifact-side-effect-free sandbox. A loop dry run still initializes and updates loop state and logs. Before target execution, approved L2/L3 policy actions can resume or restart an incomplete run, and `regenerate_missing_summary` can write to an existing run directory. The checked-in `unified_regression_guard` profile enables both automatic resume and stale-failure restart.

Inspect the profile's recovery authority and any existing target run artifacts first. When preservation matters, validate with disposable or uniquely named profile, target, and run paths. Never assume `--dry-run` protects existing run artifacts from changes.

Run one profile cycle in the default dry-run mode:

```bash
uv run ase loop run --profile "$PROFILE_ID" --dry-run
```

Alternatively, validate scheduler behavior with one immediate cycle:

```bash
uv run ase loop start --profile "$PROFILE_ID" --once --dry-run
```

Review `outputs/loops/STATE.md`, `outputs/loops/loop-budget.md`, and `outputs/loops/loop-run-log.md` before enabling live calls.

## Start recurring operation

Start one profile on its configured cadence:

```bash
uv run ase loop start --profile "$PROFILE_ID" --no-dry-run
```

Coordinate all checked-in profiles:

```bash
uv run ase loop start --all --no-dry-run
```

For a bounded operational trial, add `--max-cycles <n>`. Use `--interval-seconds <n>` only for deliberate manual or test-time cadence overrides. `--profile` and `--all` are alternatives.

## Kill switch

Persistently pause a profile:

```bash
uv run ase loop pause \
  --profile "$PROFILE_ID" \
  --reason "maintenance or incident reference"
```

Confirm the paused state:

```bash
uv run ase loop status --profile "$PROFILE_ID"
```

Pause state is checked before subsequent scheduler cycles are admitted. It does not cancel a target or cycle already executing. For in-flight containment, follow the deployment incident procedure and separately stop the scheduler or active process and, where applicable, the target execution.

After the incident is resolved, resume explicitly:

```bash
uv run ase loop resume --profile "$PROFILE_ID"
```

## Audit and routine checks

Audit one profile or the full profile directory:

```bash
uv run ase loop audit --profile "$PROFILE_ID"
uv run ase loop audit
```

During operation, check:

- `outputs/loops/STATE.md` for status, pause reason, last checker result, planner/reflection output, and human inbox items.
- `outputs/loops/loop-budget.md` for current daily/weekly usage and profile caps.
- `outputs/loops/loop-run-log.md` for chronological cycle, action, pause, and run events.
- `outputs/loops/state/<profile_id>.json` when machine-readable detail is needed.
- `outputs/runs/<run_id>/` for the underlying evaluation artifacts of a referenced run.

`uv run ase loop status --profile "$PROFILE_ID"` is the fastest structured view of current persisted state. `uv run ase loop audit --profile "$PROFILE_ID"` checks initialized artifacts and configured safeguards.

## Failure diagnosis and recovery

1. Stop further admission with `loop pause` if the profile is not already paused.
2. Run `loop status` and record `status`, `pause_reason`, `consecutive_checker_failures`, and the most recent run IDs.
3. Inspect `outputs/loops/loop-run-log.md` for the failing target or rejected assisted action.
4. Inspect that target's `outputs/runs/<run_id>/run_state.json` and `run_summary.json` when present.
5. Correct the contract, credentials, target service, profile, or guardrail that caused the failure.
6. Re-run `loop audit` and one dry-run cycle.
7. Resume only after the dry run and persisted state are understood.

If a target run is incomplete, the loop command accepts `--incomplete-run-action ask|resume|restart|abort`; its default is `abort`. L2/L3 policy may propose a bounded resume or stale-failure restart when the checker policy permits it. Keep restart limits conservative and inspect the assisted-action log.

Scheduler failures for one profile receive bounded backoff. Other eligible profiles can continue, so diagnose each profile independently.

## Guardrail tuning

- Reduce `daily_run_cap` to constrain the number of target runs admitted per day.
- Reduce `daily_token_cap` to constrain recorded target-run token usage.
- Lower `checker_policy.safe_max_concurrency` to cap unified evaluation concurrency.
- Keep `checker_policy.max_retry_attempts` low; increase it only after identifying a transient, recoverable failure.
- Increase `checker_policy.auto_pause_after_checker_failures` only when checker noise is measured and accepted.
- Use `active_windows` to confine unattended work to approved UTC operating times; the scheduler clock is UTC.
- Treat `allow_auto_resume` and `allow_auto_restart_stale_failed` as explicit recovery authority; disable either when human approval is required.

After any profile change, run `loop audit` and a dry-run cycle before returning to live recurring operation. Initialized state retains persisted `active_windows` and daily cap values; confirm them with `loop status` and use a controlled state migration when those values change instead of assuming `loop init` overwrites them.
