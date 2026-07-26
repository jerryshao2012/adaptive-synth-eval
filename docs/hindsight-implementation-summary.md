# Hindsight-Style Triggered Monitoring

This implementation applies triggered selection to an existing run's
`chat_history.jsonl`. Continuous ingestion from Cosmos DB is intentionally
deferred; a future source adapter can feed the same normalized row contract.

## Implemented behavior

- Trigger rules are declarative YAML with stable `rule_id` values. The packaged
  policy is loaded with `importlib.resources`; `--trigger-policy` supplies a
  complete replacement. Rules and agent-emitted events can be disabled
  explicitly, and those controls participate in the policy fingerprint.
- Agent-emitted `capture_events`, native row signals, and deterministic
  heuristics produce typed, idempotent triggers with policy provenance.
- Selection is stateful per conversation. Interleaved conversations never
  become one another's context; lookback crosses processing windows and pending
  lookahead survives resume.
- `--sample-size` is the one hard capture budget for each processing window.
  Trigger rows rank first, then context by associated severity, distance,
  before/after role, and source line. A selected row retains every association.
- Selection has its own fingerprint covering the trigger policy, lookback,
  lookahead, sample size, and selector algorithm version. A change automatically
  restarts selection without invalidating reusable metric values.
- Monitoring writes idempotent trigger and promotion journals. Legacy rows with
  no rich local locator are recorded as `unavailable_missing`; expired locators
  are recorded as `unavailable_evicted`. Production chat rows resolve their
  locators through stable skeleton IDs without adding local paths to canonical
  chat history.
- Score files are atomically replaced before monitoring state advances. A retry
  can replay journal writes safely because journal IDs are deduplicated.
- Target latency, availability, guardrail latency, and trace/tool errors populate
  `system_reliability`, including HTTP status and telemetry retained in
  `response_raw`. Evaluator time is separate under `evaluation_runtime`; absent
  telemetry remains `null`/`unknown`.

## Optional production capture

Set `ASE_CAPTURE_ENABLED=true` when running synth or unified evaluation to emit
rich records into bounded per-producer files under `capture/local/` and compact
skeletons into `capture/skeleton.jsonl`. The default retention is 1000 records
per producer and can be changed with
`ASE_CAPTURE_MAX_RECORDS_PER_PRODUCER`.

Chat-history writes, unified persona-memory commits, and attack-memory commits
are wired to optional run-scoped adapters. Capture failures are logged and do
not roll back the authoritative artifact.

## Main files

- `src/adaptive_synth_eval/capture/`
- `src/adaptive_synth_eval/monitoring/triggers.py`
- `src/adaptive_synth_eval/monitoring/selection.py`
- `src/adaptive_synth_eval/monitoring/runner.py`
- `ai-eval-dashboard/lib/monitoring-config.ts`

Verification results are intentionally not hard-coded here. Use the commands in
the implementation plan or run the current Python and dashboard test suites.
