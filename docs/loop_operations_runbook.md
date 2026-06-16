# Loop Operations Runbook

## Scope

This runbook covers unattended `ase loop` operation for L3 profiles.

## Preconditions

- Loop profiles must declare `readiness_level: L3`.
- Each unattended profile should define:
  - `active_windows`
  - `priority`
  - `daily_run_cap` and/or `daily_token_cap`
  - `checker_policy.auto_pause_after_checker_failures`
- Persistent assets must be initialized with `ase loop init --profile <id>`.

## Recommended Startup

Run all checked-in unattended profiles once for validation:

```powershell
ase loop start --all --once --profiles-dir loops/profiles --output-dir outputs
```

Start recurring unattended coordination:

```powershell
ase loop start --all --profiles-dir loops/profiles --output-dir outputs
```

## Kill Switch

Pause a profile immediately:

```powershell
ase loop pause --profile <id> --reason "manual pause" --profiles-dir loops/profiles --output-dir outputs
```

Resume a paused profile:

```powershell
ase loop resume --profile <id> --profiles-dir loops/profiles --output-dir outputs
```

## Audit

Check unattended readiness and safeguards:

```powershell
ase loop audit --profile <id> --profiles-dir loops/profiles --output-dir outputs
ase loop audit --profiles-dir loops/profiles --output-dir outputs
```

## Operational Expectations

- Paused profiles are skipped by both single-profile and multi-profile schedulers.
- Profiles outside `active_windows` are skipped until they re-enter the allowed window.
- Profiles are coordinated in ascending `priority` order.
- Repeated checker failures trigger auto-pause when the configured threshold is reached.
- Daily run or token cap breaches auto-pause the profile.
- Escalations should appear in `outputs/loops/STATE.md` and `outputs/loops/loop-run-log.md`.

## Recovery

1. Inspect `outputs/loops/STATE.md` for `pause_reason`, recent runs, and human inbox items.
2. Inspect `outputs/loops/loop-run-log.md` for assisted actions and cycle outcomes.
3. Inspect the latest target run directory under `outputs/runs/<run_id>/`.
4. Adjust the loop profile or clear the incident cause.
5. Resume the profile with `ase loop resume --profile <id>`.

## Guardrail Tuning

- Tighten `daily_run_cap` to reduce runaway unattended execution.
- Tighten `daily_token_cap` if LLM spend needs stronger containment.
- Increase `checker_policy.auto_pause_after_checker_failures` only if the checker is noisy and false positives are understood.
- Use `active_windows` to keep unattended runs inside business-approved time ranges.
