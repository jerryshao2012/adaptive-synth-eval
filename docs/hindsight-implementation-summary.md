# Hindsight-Style Triggered Monitoring

## Update summary

This update implements Hindsight-style triggered selection for existing
evaluation runs. Instead of evaluating randomly sampled rows, monitoring keeps a
compact record of activity, detects meaningful triggers, and promotes the
triggered turn plus the most relevant same-conversation context for evaluation.

The implementation currently reads completed or growing
`chat_history.jsonl` artifacts. Continuous ingestion from Cosmos DB is
intentionally deferred. Because the Cosmos container schema and indexing are
under project control, a future adapter can query by conversation and event
order, normalize documents into the existing monitoring row contract, and reuse
the trigger, selection, budget, state, and provenance layers implemented here.

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

## Review findings resolved

- **Package import:** the capture package imports the correctly named
  `producers.py` module, allowing the Python suite to collect normally.
- **Conversation-safe context:** selection is keyed by conversation rather than
  adjacent file rows. Per-conversation lookback crosses windows, and unresolved
  lookahead is persisted for later input.
- **Hard capture budget:** trigger rows are selected first, followed by nearest
  context in deterministic order. Context is trimmed to `sample_size`, and
  dropped candidates are counted.
- **Policy reconciliation and provenance:** normalized trigger and selection
  fingerprints are persisted and consumed. Policy changes restart selection
  while reusable metric scores remain valid. Selected records retain trigger
  IDs, source, role, and policy provenance.
- **Production capture wiring:** synth chat output, unified chat output, persona
  memory, and attack memory can emit through a run-scoped capture coordinator.
- **Durable local-first storage:** rich records use bounded per-producer JSONL
  buffers with stable locators instead of process-only memory.
- **Concurrent JSONL safety:** sinks append under locking, avoid whole-file
  rewrites, and use idempotent journal identifiers.
- **Production reliability telemetry:** target latency, availability, HTTP
  status, guardrail latency, and trace/tool errors feed `system_reliability`;
  evaluator runtime is reported separately.
- **Representative tests:** integration tests import production trigger and
  selector code and assert exact budget ordering, continuity, reconciliation,
  provenance, persistence, and reliability behavior.

## Optional production capture

Set `ASE_CAPTURE_ENABLED=true` when running synth or unified evaluation to emit
rich records into bounded per-producer files under `capture/local/` and compact
skeletons into `capture/skeleton.jsonl`. The default retention is 1000 records
per producer and can be changed with
`ASE_CAPTURE_MAX_RECORDS_PER_PRODUCER`.

Chat-history writes, unified persona-memory commits, and attack-memory commits
are wired to optional run-scoped adapters. Capture failures are logged and do
not roll back the authoritative artifact.

## Dashboard update

The dashboard supports triggered monitoring configuration, capture-budget
labeling, lookback/lookahead controls, trigger and promotion metadata, nullable
reliability values, and triggered-run status counters.

This update also restores dashboard server functionality that had been
accidentally removed during an earlier monitoring refactor:

- human-review queue, detail, bulk action, persistence, and statistics APIs;
- artifact validation, readiness, and freshness helpers;
- the exported monitoring POST handler used by route tests;
- React-safe theme initialization and a stable review-table sort component; and
- local Geist fonts so production builds do not depend on Google font downloads.

At the time of this update, the dashboard has 306 passing Vitest tests, zero
ESLint errors, and a successful production build and TypeScript check. ESLint
still reports 26 non-blocking unused-code and hook-dependency warnings. Next.js
also reports a non-failing file-tracing warning because server routes
intentionally resolve evaluation artifacts from the parent repository.

## Deferred Cosmos DB continuous monitoring

The next phase is a Cosmos DB source adapter, not a second trigger engine. The
adapter should:

1. query a controlled container by partition key, conversation ID, and monotonic
   event position or timestamp;
2. checkpoint the Cosmos continuation token together with monitoring state;
3. normalize each document into the existing row and telemetry contracts;
4. preserve pending lookahead across polling cycles; and
5. pass normalized rows into the same deterministic trigger and selection
   pipeline.

Recommended container design details - partition key, ordering field, document
shape, retention, and indexes - remain open until the telemetry workload is
defined. No Cosmos SDK dependency or continuous polling loop is included in this
update.

## Main files

- `src/adaptive_synth_eval/capture/`
- `src/adaptive_synth_eval/monitoring/triggers.py`
- `src/adaptive_synth_eval/monitoring/selection.py`
- `src/adaptive_synth_eval/monitoring/runner.py`
- `ai-eval-dashboard/lib/monitoring-config.ts`
- `ai-eval-dashboard/lib/server/reviews.ts`
- `ai-eval-dashboard/lib/server/validation.ts`
