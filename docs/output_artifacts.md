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
└── personas/
	└── <persona_id>_memory.md  # Synth and unified persona memory files
```

Notes:
- `synth` mode produces the common simulation artifacts and omits unified-only files.
- `unified` mode produces common artifacts plus unified-specific files listed above.
- Score, state, and progress artifacts (`monitoring_scores.jsonl`,
  `monitoring_state.json`, and `eval_progress.md`) are created by
  `ase monitor run` against the run folder. `monitoring.log` is created when the
  dashboard launches monitoring, or when a terminal command is explicitly
  redirected to that path.

For **unified runs**, `contract.normalized.json` uses canonical unified contract schema version 2. Provider
settings are emitted in nested `azure`, `bedrock`, and `ollama` blocks, schedules are
fully serialized, and literal target authentication values are redacted.
The parser also accepts schema-v1 contracts and legacy flat `LLMSpec` fields, including
`bedrock_endpoint`, at the top-level, component, and target LLM locations. If a nested and
legacy field conflict, the nested value wins with a warning. Unsupported future schema
versions fail validation. `judge_overrides` is round-tripped with a warning but is not
currently applied to judge behavior. Synth runs serialize their separate synth contract
shape and do not label it unified schema version 2.

For **unified runs**, `run_state.json` version 2 tracks completed conversation IDs, rolling metrics, actual
token/component usage, committed attack memory, and fingerprints of both the effective
contract and exact filtered run plan. Resume rejects a changed v2 contract or plan;
legacy v1 state remains best-effort with a warning. Transient in-flight token
reservations are deliberately not persisted. Synth runs currently write run-state
version 1; the unified v2 fingerprint and memory semantics do not apply to synth state.

For **unified runs**, `run_plan.json` is the exact ordered and filtered conversation plan,
including each resolved turn schedule. The plan and canonical secret-safe contract are
independently fingerprinted with SHA-256 in unified run-state version 2. Synth also emits
a run plan, but it is not covered by these unified-v2 fingerprint claims.

Budget-driven unified runs are currently sequential. Finite plans use a bounded sliding
window, with per-turn reservations acquired by a conversation task immediately before
turn work. If an admitted task cannot reserve its first turn, no zero-turn conversation
row is written and its ID is not marked complete.

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
`session_policy`, `budget_exhausted`, `stopped`, and `runner_exception` where applicable.

When trajectory mode is enabled, `run_summary.json` adds `trajectory` with
`max_trace_severity_score`, `mean_trace_severity_score`, `sessions_with_signal`, and
`failure_surface_counts`. Empty traces stay response-only and do not call the summarizer.
The current mean is calculated from positive trace-severity signals only; zero-severity
meaningful traces are not included.

### Attack memory artifact

`attack_memory.json` is written for `shared` and `per_persona` modes and omitted for
`none`. Shared mode stores one `entries` array. Per-persona mode stores a `personas` map,
with one independently capped memory payload per persona. Entries include the legacy
response-only `failure_score` plus `effective_failure_score` and `failure_threshold`;
legacy entries default the effective score to their response score and the threshold to
`3`.

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

### Monitoring state and dashboard log

`monitoring_state.json` is the resumable checkpoint and the dashboard's source
for saved launch defaults. Its operational fields include `sample_size`,
`interval_minutes`, `sampling_strategy`, and nullable `max_windows`, alongside
`status`, `next_line_index`, row/window counts, source identity, provider, and
evaluation/policy fingerprints. `eval_progress.md` presents the same progress in
human-readable form, including the saved maximum-window setting.

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
| `error` | `str` | HTTP or backend client error string (if failed) |
| `synthetic_flag` | `bool` | True if synthetic generation |

### Optional and metadata fields

- `retrieved_policy_ids` (`list`): List of document or policy IDs retrieved by the target bot.
- `response_raw` (`dict`): The raw JSON payload returned by the chatbot endpoint.
- `generation_metadata` (`dict`): Generation metadata; unified rows include turn type (`synth` or `adversarial`) and adversarial strategy fields where applicable.

`response_raw` is retained in `chat_history.jsonl` but intentionally omitted from the
CSV field list. `retrieved_policy_ids` and `generation_metadata` are present in both
formats when available.
