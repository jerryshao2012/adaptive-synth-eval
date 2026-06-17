# Loop Engineering for Adversarial Adaptive Synthetic Evaluation

Date: 2026-06-10
Last Updated: 2026-06-16

## 1. Purpose

This document is the cleaned, current source of truth for loop engineering in `adaptive-synth-eval`.

- continuously evaluate target chatbot behavior with adaptive synthetic and adversarial traffic,
- reason over prior outcomes,
- apply constrained recoveries under checker guardrails,
- run unattended with strict pause/budget/safety controls at L3.

## 2. Readiness Model and Current Status

Readiness levels used in this repo:
- `L0`: static contract execution (`ase run`)
- `L1`: report-only loops with planner + reflection
- `L2`: assisted actions with maker/checker enforcement
- `L3`: unattended loops with kill switch, caps, and coordination

## 3. Implemented Architecture

### 3.1 Runtime modules

Loop runtime lives under `src/adaptive_synth_eval/loop/`:
- `profiles.py`: profile schema parsing and validation
- `state_store.py`: durable loop state + markdown/log artifacts + pause/resume state updates
- `planner.py`: planner/reflection reasoning via `LLMClient` with deterministic fallback
- `policy.py`: assisted-action planning, denylist and retry policy logic
- `verifier.py`: checker decisions and rejection behavior
- `scheduler.py`: single-profile scheduler + multi-profile coordinator (priority/backoff/window-aware)
- `audit.py`: readiness/safeguards report generation

CLI wiring is in `src/adaptive_synth_eval/cli.py` under the `loop` command group.

### 3.2 Core loop flow

1. Load profile and initialize loop assets.
2. Read persisted loop state.
3. Planner proposes next target(s) and rationale.
4. Policy engine proposes assisted actions (if eligible).
5. Checker approves/rejects target/action plan.
6. Execute target run via existing `ase run` internals.
7. Reflect on outcomes.
8. Persist state, markdown summaries, and append-only log.

At `L3`, preflight controls are enforced before execution:
- kill switch (`paused`),
- daily run/token caps,
- active window eligibility.

## 4. Loop CLI Commands

Supported commands:
- `ase loop init --profile <id> [--profiles-dir loops/profiles --output-dir outputs]`
- `ase loop run --profile <id> [--dry-run|--no-dry-run]`
- `ase loop start --profile <id> [--once] [--max-cycles N]`
- `ase loop start --all [--once] [--max-cycles N]`
- `ase loop status [--profile <id>]`
- `ase loop audit [--profile <id>]`
- `ase loop pause --profile <id> [--reason "..."]`
- `ase loop resume --profile <id>`

Backward compatibility retained:
- `validate-contract`
- `run`
- `summarize`

## 5. Profile Schema (Current)

Loop profiles are stored under `loops/profiles/*.yaml`.

Common fields:
- `profile_id`
- `readiness_level` (`L1|L2|L3`)
- `cadence`
- `targets`
- `max_iterations_per_cycle`
- `budget_policy_ref`
- `human_gates`
- `denylist`
- `checker_policy`
- `llm_config`

L3-focused fields:
- `paused`
- `priority`
- `active_windows`
- `daily_run_cap`
- `daily_token_cap`

Notes:
- `checker_policy` governs retry and auto-pause thresholds.
- `targets` are validated against contract path existence.

## 6. Persisted Artifacts

Runtime artifacts are under `outputs/loops/`:
- `STATE.md`: human-readable loop status and inbox
- `loop-budget.md`: run/token budget snapshots
- `loop-run-log.md`: append-only loop event history
- `state/<profile_id>.json`: durable machine-readable loop state

Key persisted state includes:
- planner/reasoning/reflection outputs
- checker decisions
- assisted action history and attempts
- pause status and reason
- consecutive checker failure count
- budget counters and cap references

## 7. L2 and L3 Control Guarantees

### 7.1 L2 assisted loop guarantees

- Maker/checker split enforced in code path.
- Checker rejection hard-fails loop cycle.
- Denylist can veto risky target/action classes.
- Max retry attempts per action are enforced.
- Assisted actions are logged to `loop-run-log.md`.

### 7.2 L3 unattended loop guarantees

- Manual kill switch (`pause` / `resume`) is persistent.
- Auto-pause on repeated checker failures (threshold-driven).
- Auto-pause when daily run or token caps are breached.
- Active-window gating for unattended schedules.
- Multi-profile coordination honors priority ordering.
- Backoff is applied after per-profile failures.

## 8. Example Profiles in Repo

Current checked-in examples include:
- `loops/profiles/daily_triage.yaml`
- `loops/profiles/unified_regression_guard.yaml`

`unified_regression_guard` is the primary L3-style unattended profile template.

## 9. Operations and Runbook

Operational guide:
- `docs/loop_operations_runbook.md`

Recommended unattended startup:
- `ase loop start --all --profiles-dir loops/profiles --output-dir outputs`

Recommended readiness check:
- `ase loop audit --profiles-dir loops/profiles --output-dir outputs`

## 10. Test Coverage Summary

Loop-focused test coverage includes:
- profile parsing/validation
- scheduler cadence and coordination behavior
- planner/reflection fallback and LLM paths
- CLI loop command flows
- policy/verifier behavior and rejection gates
- pause/resume and L3 cap/failure auto-pause behavior

Recent focused command used in development:
- `.\.venv\Scripts\python.exe -m pytest tests/unit/test_loop_profiles.py tests/unit/test_loop_reasoner.py tests/unit/test_loop_scheduler.py tests/unit/test_loop_cli.py tests/unit/test_loop_policy.py tests/unit/test_cli.py -q`

## 11. Optional Follow-up Work (Not Required for Current L3)

Potential enhancements that are intentionally optional:
- structured reasoning audit stream (for example `reasoning-audit.jsonl`)
- richer active-window syntax and timezone controls
- external escalation connectors (Jira/Slack/GitHub)
- long-duration unattended soak dashboards

## 12. Definition of Done (Current)

Loop engineering is considered complete for this repository when:
- loop commands are production-usable and documented,
- L1/L2/L3 profiles can run with expected safeguards,
- state, logs, and budget artifacts provide traceability,
- maker/checker controls are enforced where required,
- unattended operation is guarded by kill switch + caps + failure auto-pause,
- non-loop CLI behavior remains backward compatible.
