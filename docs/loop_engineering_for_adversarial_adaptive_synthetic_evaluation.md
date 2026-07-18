# Loop Engineering

This guide is the conceptual reference for continuous evaluation loops in Adaptive Synth Eval. For startup, incident response, and routine operation, use the [Loop operations runbook](loop_operations_runbook.md).

## Readiness model

The readiness level controls how much authority a loop may exercise:

- `L0`: direct, one-shot contract execution with `ase run`; it is not a loop profile level.
- `L1`: report-only looping with planner selection and post-run reflection.
- `L2`: assisted actions guarded by a maker/checker split.
- `L3`: unattended scheduling with persistent pause state, active windows, budget caps, and multi-profile coordination.

Loop profile parsing accepts `L1`, `L2`, and `L3`. A direct evaluation remains the `L0` baseline.

## Module architecture

Loop runtime code lives in `src/adaptive_synth_eval/loop/`:

- `profiles.py` parses and validates checked-in profiles and their targets.
- `planner.py` selects targets and reflects on outcomes through an `LLMClient`, with deterministic fallback behavior.
- `policy.py` proposes bounded assisted actions for L2 and L3 profiles.
- `verifier.py` applies the checker decision before target execution.
- `scheduler.py` runs one profile or coordinates multiple profiles by priority, active window, and failure backoff.
- `state_store.py` persists machine-readable state and renders operator-facing state, budget, and log files.
- `audit.py` reports profile readiness, safeguards, and required artifact availability.

The `loop` command group in `src/adaptive_synth_eval/cli.py` connects these modules to the existing evaluation runner. It does not introduce a separate contract executor.

## Cycle model

A loop cycle follows this control flow:

1. Load the profile and persisted state.
2. Enforce L3 preflight controls when applicable.
3. Ask the planner to select targets and explain the selection.
4. Let the policy engine propose eligible assisted actions.
5. Require checker approval for L2 and L3 target/action plans.
6. Execute selected contracts through the existing `ase run` internals.
7. Reflect on run results.
8. Persist the outcome, budget counters, assisted-action history, and operator artifacts.

Without a configured or available reasoning model, planning and reflection use deterministic report-only fallbacks.

## Control guarantees

### L1 report-only behavior

- The planner can select configured targets and record its rationale.
- The loop runs the selected evaluation contracts and records reflection output.
- No assisted recovery action is proposed by the policy engine.

### L2 assisted behavior

- Policy and checker are separate steps in the execution path.
- A denylist match rejects target execution.
- High-risk or blocked assisted actions are rejected.
- Per-action retry limits are enforced from `checker_policy.max_retry_attempts`.
- Approved actions and their outcomes are written to the loop log.

Supported assisted actions include safe resume of incomplete runs, bounded restart of stale failed runs, unified concurrency caps, and regeneration of missing summaries.

### L3 unattended behavior

L3 adds these controls to L2:

- Persistent `pause` and `resume` state acts as an admission kill switch for subsequent scheduler cycles.
- Active windows gate scheduled execution.
- Daily run and token caps are checked before a cycle and can auto-pause a profile after a cycle reaches a cap.
- Consecutive checker failures can auto-pause a profile.
- Multi-profile scheduling orders profiles by ascending `priority` value.
- A failed profile receives bounded exponential backoff without preventing other eligible profiles from running.

The scheduler reads pause state before starting each cycle. Pausing does not cancel a target or cycle already in progress; stopping in-flight work requires separately stopping the scheduler or active process and following the deployment's target-execution incident procedure.

The readiness audit checks that an L3 profile has initialized artifacts, at least one daily cap, an active window, and a positive checker-failure threshold. It reports configuration readiness; it does not replace operational review.

## Profile schema

Profiles are YAML or JSON files under `loops/profiles/` by default.

Required fields:

- `profile_id`: stable profile identifier.
- `readiness_level`: `L1`, `L2`, or `L3`.
- `cadence`: cron-like cadence or an interval understood by the scheduler.
- `targets`: non-empty list of target mappings; each target requires an existing `contract` path and may select `persona`, `scenario`, `adversarial_scenario`, or `dry_run`.

Common optional fields:

- `max_iterations_per_cycle`
- `budget_policy_ref`
- `human_gates`
- `escalation_rules`
- `denylist`
- `checker_policy`
- `llm_config`

L3 scheduling and containment fields:

- `paused`
- `priority`
- `active_windows`, such as `MON-FRI@08:00-18:00` (evaluated against the scheduler's UTC clock)
- `daily_run_cap`
- `daily_token_cap`

`llm_config` requires `provider` and `model_name` when present. It can also set `endpoint_url`, `max_tokens_per_call`, `temperature`, and `fallback_provider`.

Relevant `checker_policy` keys include `max_retry_attempts`, `safe_max_concurrency`, `allow_auto_resume`, `allow_auto_restart_stale_failed`, `stale_failed_restart_after_minutes`, and `auto_pause_after_checker_failures`.

The checked-in examples are:

- `loops/profiles/daily_triage.yaml` — an L1 report-only profile.
- `loops/profiles/unified_regression_guard.yaml` — an L3 unattended profile with active-window, budget, and checker controls.

## Artifact model

Initializing a profile creates shared operator views in the runtime output tree (by default, outputs/loops/) and one durable state file per profile:

- `STATE.md`: status, targets, pause reason, latest reasoning/reflection, recent runs, and human inbox.
- `loop-budget.md`: daily and weekly run/token counters plus configured caps.
- `loop-run-log.md`: append-only initialization, pause/resume, assisted-action, run, and cycle events.
- `state/<profile_id>.json`: machine-readable profile state, recent cycles, budget counters, checker failures, and assisted-action attempts.

Target evaluation artifacts continue to live under `outputs/runs/<run_id>/`; the loop state references their outcomes rather than replacing them.

## Operational interface

The available loop commands are `init`, `run`, `start`, `status`, `audit`, `pause`, and `resume`. See the [CLI command map](cli_usage.md#loop-command-map) for a compact list and the [operations runbook](loop_operations_runbook.md) for safe operating procedures.
