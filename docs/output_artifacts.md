# Output Artifacts & Schemas

This is the schema authority for files emitted by evaluation and monitoring runs. For workflow instructions, see the [CLI guide](cli_usage.md), [unified evaluation guide](unified_evaluation.md), and [monitoring guide](monitoring.md). Contract fields are defined separately in the [contract reference](contracts.md).

With the default output configuration, simulation outputs and evaluation summaries are written under `outputs/runs/<run_id>/`. A custom `output.base_dir` changes the base location.

## Directory Structure

A completed simulation run writes artifacts under the run folder. Some files are common to all runs, while others are mode- or feature-specific.

```text
outputs/runs/<run_id>/
├── contract.normalized.json    # Resolved contract snapshot used for the run
├── run_plan.json               # Planned conversation list/inputs for this run
├── run_state.json              # In-progress/completed checkpoint and metrics
├── run_summary.json            # Final summary payload
├── generation_report.md        # Human-readable markdown report
├── chat_history.jsonl          # Per-turn canonical chat history (JSONL)
├── chat_history.csv            # Per-turn canonical chat history (CSV)
├── conversations.jsonl         # Per-conversation rows
├── turns.jsonl                 # Per-turn unified/synth turn rows
├── scores.jsonl                # Per-turn score rows
├── conversations.txt           # Optional transcript view (--output-conversations)
├── run.log                     # Unified mode run log (trajectory + orchestrator logs)
├── failed_examples.jsonl       # Unified mode: failed adversarial examples
├── adversarial_sessions.jsonl  # Unified mode: adversarial session records
├── attack_memory.json          # Unified mode: shared/per-persona attack memory snapshot
├── monitoring_scores.jsonl     # Monitoring output (ase monitor run)
├── monitoring_state.json       # Monitoring resume/checkpoint state
├── eval_progress.md            # Monitoring progress/status markdown
├── monitoring.log              # Append-only dashboard-launched CLI output
├── capture/
│   ├── local/<producer>.jsonl  # Optional bounded rich producer buffers
│   ├── skeleton.jsonl          # Compact records with durable locators
│   ├── envelopes.jsonl         # Rich records resolved during promotion
│   ├── triggers.jsonl          # Idempotent detected-trigger journal
│   └── promotions.jsonl        # Promotion outcomes, including unavailable rows
└── personas/
	├── <persona_id>_memory.json # Unified authoritative, versioned actor state
	└── <persona_id>_memory.md   # Synth state / unified compatibility view
```

Notes:
- `synth` mode produces the common simulation artifacts and omits unified-only files.
- `unified` mode produces common artifacts plus unified-specific files listed above.
- In unified mode, persona-memory JSON is the resumable source of truth. The adjacent
  Markdown file is regenerated as a human-readable compatibility view. Legacy Markdown
  is imported automatically when no JSON sidecar exists.
- Score, state, and progress artifacts (`monitoring_scores.jsonl`,
  `monitoring_state.json`, and `eval_progress.md`) are created by
  `ase monitor run` against the run folder. `monitoring.log` is created when the
  dashboard launches monitoring, or when a terminal command is explicitly
  redirected to that path.

For **unified runs**, `contract.normalized.json` uses canonical unified contract schema version 3. Provider
settings are emitted in nested `azure`, `bedrock`, and `ollama` blocks, schedules are
fully serialized, and literal target authentication values are redacted.
The parser also accepts schema-v1 and schema-v2 contracts and legacy flat `LLMSpec` fields, including
`bedrock_endpoint`, at the top-level, component, and target LLM locations. If a nested and
legacy field conflict, the nested value wins with a warning. Unsupported future schema
versions fail validation. `judge_overrides` is round-tripped with a warning but is not
currently applied to judge behavior. Synth runs serialize their separate synth contract
shape and do not label it with a unified schema version.

For **unified runs**, `run_state.json` version 2 tracks completed conversation IDs, rolling metrics, actual
token/component usage, committed attack memory, and fingerprints of both the effective
contract and exact filtered run plan. Resume rejects a changed v2 contract or plan;
legacy v1 state remains best-effort with a warning. Transient in-flight token
reservations are deliberately not persisted.

**Unprofiled legacy synth runs** continue to write run-state version 1 and do not make
contract- or plan-fingerprint guarantees. **Profiled synth runs** write run-state
version 2 with SHA-256 fingerprints of the normalized synth contract and the exact
serialized full run plan. On resume, profiled synth requires a version 2 checkpoint and
validates both fingerprints before any writer or artifact mutation; a changed effective
contract or full plan rejects resume and requires a restart. Unified memory and token-
reservation semantics remain specific to unified runs.

For **unified runs**, `run_plan.json` is the exact ordered and filtered conversation plan,
including each resolved turn schedule. The plan and canonical secret-safe contract are
independently fingerprinted with SHA-256 in unified run-state version 2. For **profiled
synth runs**, `run_plan.json` contains the exact serialized full profiled plan, and its
fingerprint is computed before completed conversations are filtered during resume. Run
plans from unprofiled legacy synth runs remain outside these fingerprint guarantees.

Budget-driven unified runs are currently sequential. Finite plans use a bounded sliding
window, with per-turn reservations acquired by a conversation task immediately before
turn work. If an admitted task cannot reserve its first turn, no zero-turn conversation
row is written and its ID is not marked complete.

### Time-profile provenance

When a contract contains `time_profile`, the run plan and downstream artifacts carry
the selected phase and recipe. These fields are optional so artifacts from contracts
that omit `time_profile` retain their legacy shape.

| Field | Type | Meaning |
| :--- | :--- | :--- |
| `sequence` | `int` | Stable 1-based profiled plan order |
| `recipe_id` | `str` | Selected synth mix item or unified eval-plan entry |
| `synthetic_timestamp` | `str` | Conversation anchor inside its period, serialized with Python `datetime.isoformat()` |
| `synthetic_slot` | `int` | 1-based conversation slot within the daily period instance |
| `profile_period_id` | `str` | Recurring window ID from the contract |
| `profile_period_instance_id` | `str` | Daily instance ID, exactly `<YYYY-MM-DD>/<period_id>` |
| `profile_period_start` | `str` | Daily instance start as an ISO local datetime |
| `profile_period_end` | `str` | Daily instance end as an ISO local datetime |
| `conversation_mode` | `str` | Contract label used to group the window |
| `behavior_mode` | `str` | Planned simulated-user style for the window |
| `traffic_weight` | `float` | Window weight used for conversation allocation |
| `recipe_weights` | `object` | Complete configured recipe-weight map for the window |
| `timestamp` | `str` | Artifact event time; turn-specific for per-turn rows and the conversation anchor for conversation rows |

The timestamp strings are timezone-naive ISO 8601 local synthetic times, for example
`2026-08-03T10:00:00`; fractional seconds appear only when the deterministic allocation
requires them. If an instance contains `N` conversations, slot `s` receives:

```text
period_start + (period_end - period_start) * s / (N + 1)
```

Within a conversation, turn 1 uses that anchor. Later turns increase by at most one
second each and never pass `profile_period_end`. `synthetic_timestamp` remains the
conversation anchor on every turn, while `timestamp` is the turn event time.

Field propagation is intentionally artifact-specific:

| Artifact | Profile metadata |
| :--- | :--- |
| `run_plan.json` | All fields above except event `timestamp`; includes the exact ordered profiled plan |
| `chat_history.jsonl` | All provenance fields, including turn `timestamp` |
| `chat_history.csv` | Appends the same profile columns to the legacy header |
| `turns.jsonl` | All provenance fields, including turn `timestamp` |
| `scores.jsonl` | All provenance fields, including turn `timestamp` |
| `conversations.jsonl` | All provenance fields; `timestamp` is the conversation anchor |
| `monitoring_scores.jsonl` | Copies the source `timestamp`, `recipe_id`, `profile_period_id`, `profile_period_instance_id`, `profile_period_start`, `profile_period_end`, `conversation_mode`, `behavior_mode`, `synthetic_slot`, `synthetic_day`, `scenario_id`, `adversarial_scenario_id`, and `persona_id` when present |

Profiled `run_summary.json` also adds `profile_counts`, grouped by period, daily
period instance, recipe, conversation mode, and behavior mode.

CSV compatibility is mode-stable: unprofiled runs keep the pre-profile CSV header and
do not emit empty profile columns. Profiled runs append the profile columns. Resume
refuses to append if the existing CSV header does not match the active profile mode,
preventing a file from silently mixing schemas.

Unified adversarial rows in `scores.jsonl` and `turns.jsonl` retain the response-only
`failure_score`/`best_failure_score` and add `effective_failure_score`,
`best_effective_failure_score`, `failure_threshold`, and `is_breach`. Effective scores
are the maximum of response and trajectory severity, so trajectory-only breaches are
reported without changing response-score semantics.

### Unified adversarial score fields

`scores.jsonl` is the authoritative normalized verdict artifact. Every adversarial score
row includes:

| Field group | Fields |
| :--- | :--- |
| Response verdict | `failure_score`, `refusal_quality`, `harm_potential`, `specificity`, `refusal_score`, `guardrail_worked`, `near_miss`, `confidence` |
| Explanation/error | `failure_type`, `short_reason`, `reasoning`, `judge_error` |
| Trajectory verdict | `trace_severity_score`, `overall_severity_score`, `trajectory_risk`, `failure_surface`, `tool_call_risk_score`, `unsafe_delegation_score`, `instruction_priority_violation` |
| Outcome | `best_failure_score`, `effective_failure_score`, `best_effective_failure_score`, `failure_threshold`, `is_breach` |

The outcome fields have these stable meanings:

| Field | Meaning |
| :--- | :--- |
| `failure_score` | Response-only judge score for this turn |
| `best_failure_score` | Highest response-only score in the conversation so far |
| `effective_failure_score` | `max(failure_score, trace_severity_score)` for this turn |
| `best_effective_failure_score` | Highest effective score in the conversation so far |
| `failure_threshold` | Scenario threshold, or the global adversarial threshold when the scenario omits one |
| `is_breach` | Whether this row's effective score meets this row's threshold |

`turns.jsonl` carries those six outcome fields on adversarial rows. Conversation rows and
top-level adversarial-session rows carry the best-score/threshold/breach subset, while
each adversarial-session turn carries the six turn-level fields. `failed_examples.jsonl`
contains only rows where `is_breach` is true. Full normalized verdict completeness is
guaranteed in `scores.jsonl`; other artifacts retain the verdict subsets appropriate to
their purpose.

Conversation `termination_reason` values include `completed`, `failure_threshold`,
`session_policy`, `budget_exhausted`, `skill_execution_error`, `stopped`, and
`runner_exception` where applicable.

When trajectory mode is enabled, `run_summary.json` adds `trajectory` with
`max_trace_severity_score`, `mean_trace_severity_score`, `sessions_with_signal`, and
`failure_surface_counts`. Empty traces stay response-only and do not call the summarizer.
The current mean is calculated from positive trace-severity signals only; zero-severity
meaningful traces are not included.

### Agent Skills provenance

When `attack_skills.enabled` is true, each successful adversarial row stores the selected
skill in `generation_metadata.strategy`: `skill_name`, `skill_version`,
`skill_package_digest`, and redacted `skill_tool_events`. Tool events contain the tool
name, status, and argument/result type and size summaries rather than raw inputs or
reversible hashes.

A failed skill turn is written explicitly with `failure_mode` and
`termination_reason` set to `skill_execution_error`; it also carries the selected skill
identity, safe tool events, and `skill_execution_error`. ASE does not generate or send a
legacy fallback attack for that turn.

`run_summary.json` and `generation_report.md` include `attack_methods` coverage:
angle, sub-tactic, and versioned-skill counts; unique coverage; tool utilization;
skill-execution errors; and planner calls/tokens. The existing
`failure_percentiles.failure_score` provides the judge-score distribution used with
these fields for legacy-versus-skills comparison runs.

### Attack memory artifact

`attack_memory.json` is written for `shared` and `per_persona` modes and omitted for
`none`. Shared mode stores one `entries` array. Per-persona mode stores a `personas` map,
with one independently capped memory payload per persona. Entries include the legacy
response-only `failure_score` plus `effective_failure_score` and `failure_threshold`;
skill-enabled entries also include `skill_name` and `skill_version`. Legacy entries
default the effective score to their response score, the threshold to `3`, and the skill
fields to empty strings.

> **Current limitation:** memory entries preserve their historical thresholds, but the
> planner's rendered worked/partial/refused labels currently classify aggregated scores
> against the current session threshold rather than each entry's stored threshold.

### Monitoring score version metadata

Monitoring rows in `monitoring_scores.jsonl` include `value_versions`. Its
`metrics` map stores content and policy fingerprints per metric;
`metric_groups` records each metric's evaluation group; and
`group_refresh_quality` records `llm`, `heuristic_fallback`, or `dry_run`.
The composite evaluation fingerprint remains an audit summary. Cache reuse is
determined per row and per metric group, so a material change refreshes only
the affected group. A group recorded as `heuristic_fallback` is retried on the
next monitoring run.

`ase monitor run --rescan` starts source traversal at row zero but does not
clear this file. Existing rows and metric groups remain reusable when their
value fingerprints are valid: metric content, evaluator input, and judge
identity. Only missing groups, stale-value groups, and retryable-fallback groups
invoke evaluation again. Policy fingerprints govern classification separately;
a threshold-only policy change reuses the stored numeric score and recalculates
its pass/warn/fail label without a judge call. An unchanged rescan can therefore
report zero newly evaluated rows.

Triggered rows additionally carry `selected_for_monitoring`,
`source_line_index`, `selection_fingerprint`, `trigger_policy_fingerprint`,
`selector_algorithm_version`, and `selection_provenance`. Provenance is a list
because one row can belong to overlapping trigger contexts. Each association
records trigger/rule identity, event type, detector name, reason, source,
severity, role, distance, and policy fingerprint. Reconciliation retains valid
metric values but marks rows outside the current selection inactive; dashboard
queries omit inactive cache rows.

`system_reliability` contains observed target telemetry. Missing latency or
availability evidence is `null` with status `unknown`. Availability uses
explicit errors first, then explicit availability, then the persisted target
HTTP status (including telemetry nested in `response_raw`), and finally response
presence. Evaluator elapsed time is stored separately under
`evaluation_runtime`.

### Monitoring state and dashboard log

`monitoring_state.json` is the resumable checkpoint and the dashboard's source
for saved launch defaults. Its operational fields include `sample_size`,
`interval_minutes`, `sampling_strategy`, and nullable `max_windows`, alongside
`status`, `next_line_index`, row/window counts, source identity, provider, and
evaluation/policy fingerprints. `eval_progress.md` presents the same progress in
human-readable form, including the saved maximum-window setting.

Triggered state also includes trigger-policy and selection fingerprints,
selector version, lookback/lookahead, recent conversation locators, pending
lookahead, detected/selected IDs, budget drops, and trigger counters.

### Capture storage

Production capture is opt-in with `ASE_CAPTURE_ENABLED=true`. Rich data is
written to one bounded file per producer and skeletons reference it with a
locator. The default FIFO limit is 1000 records per producer; override it with
`ASE_CAPTURE_MAX_RECORDS_PER_PRODUCER`.

Central journals use file locking, append-only writes, and stable-ID
deduplication. Monitoring resolves a production chat turn through its stable
`chat-<conversation_id>-<turn_id>` skeleton ID, so the canonical chat-history
schema does not need to embed a local path. A delayed promotion whose skeleton
or locator is absent or whose bounded record expired remains auditable as
`unavailable_missing` or `unavailable_evicted`. Rich buffers can contain
messages or memory deltas, so apply the run's normal access and retention
controls.

`monitoring.log` is append-only across dashboard Start, Continue, and
Re-evaluate launches. Each dashboard launch writes a timestamped boundary, then
connects both stdout and stderr from the detached `uv run ase monitor run`
process to the file. The dashboard log endpoint returns at most the latest
256 KiB, discarding a partial first line when the file is truncated. A CLI
process started independently in a terminal is not included unless its output
is explicitly redirected to this run-scoped file.

---

## Chat History Schema

The principal files `chat_history.jsonl` and `chat_history.csv` document every turn. They share these fields:

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `conversation_id` | `str` | Unique conversation identifier |
| `session_id` | `str` | Session ID (matches conversation_id in unified runs) |
| `synthetic_day` | `str` | Simulated ISO date of the turn |
| `persona_id` | `str` | ID of the simulating user persona |
| `scenario_id` | `str` | ID of the synthetic scenario topic |
| `turn_id` | `int` | Sequential turn index within the conversation |
| `user_message` | `str` | Text message generated by the user simulator |
| `bot_response` | `str` | Text message returned by the target chatbot |
| `expected_retrieval_topics` | `list` | Expected knowledge retrieval topics (synthetic) |
| `planned_failure_modes` | `list` | Planned failure mode injection types |
| `applied_failure_modes` | `list` | Failure mode injections successfully applied |
| `groundedness_score` | `float` | Groundedness score (synthetic turns only) |
| `relevance_score` | `float` | Relevance score (synthetic turns only) |
| `safety_score` | `float` | Safety score (synthetic turns only) |
| `clarification_score` | `float` | Clarification score (synthetic turns only) |
| `failure_mode` | `str` | Identified failure category/type (if any) |
| `latency_ms` | `float` | Turn completion latency |
| `status_code` | `int` | Target HTTP status code, when observed |
| `error` | `str` | HTTP or backend client error string (if failed) |
| `synthetic_flag` | `bool` | True if synthetic generation |

### Optional and metadata fields

- `retrieved_policy_ids` (`list`): List of document or policy IDs retrieved by the target bot.
- `response_raw` (`dict`): The raw JSON payload returned by the chatbot endpoint.
- `generation_metadata` (`dict`): Generation metadata; unified rows include turn type (`synth` or `adversarial`) and adversarial strategy fields where applicable.
- `capture_events` (`list`): Optional typed events emitted by an instrumented producer.
- Profile provenance fields: present only for contracts with `time_profile`; see
  [Time-profile provenance](#time-profile-provenance) for the complete field and
  artifact matrix.

`response_raw` is retained in `chat_history.jsonl` but intentionally omitted from the
CSV field list. `retrieved_policy_ids` and `generation_metadata` are present in both
formats when available.
