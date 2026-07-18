# Selective Metric Re-evaluation Design
> **Archive status — Implemented design history.** This document records the design that informed the current selective re-evaluation behavior. See the current [monitoring documentation](../../monitoring.md).

## Goal

Avoid re-evaluating monitoring scores for formatting-only metric-prompt edits, and re-evaluate only the affected evaluation group when a metric's scoring content genuinely changes.

## Current behavior

`compute_metric_content_fingerprint()` hashes raw `prompt_template` text alongside scoring configuration. The monitoring runner compares a single composite evaluation fingerprint in `monitoring_state.json`; if it differs, it clears every row from `monitoring_scores.jsonl`. Metrics are evaluated in grouped LLM calls (`safety` and `performance`), while each result row already records per-metric content and policy fingerprints.

## Requirements

- Formatting-only prompt edits must preserve a metric's content fingerprint.
- A material prompt/scoring change must invalidate its metric and its current evaluation group only.
- A change in one group must preserve scores in all unaffected groups.
- Threshold-only changes must continue to recompute pass/warn/fail statuses without LLM calls.
- A model identity change must invalidate all LLM-evaluated groups. Identity is the normalized provider and the existing `resolve_model_identifier()` value (Azure deployment name; `MODEL_NAME` for other configured providers; provider fallback when absent).
- Adding, removing, or moving a metric between evaluation groups must invalidate every affected group.
- Existing score files lacking per-metric fingerprints must be treated as stale once, then rewritten in the current format.
- A row refreshed with an LLM fallback must remain eligible for a later LLM retry.

## Prompt fingerprint normalization

Introduce a conservative, deterministic prompt canonicalization helper used only before prompt text is placed into the content-fingerprint payload.

The helper will:

- convert CRLF and CR line endings to LF;
- remove leading and trailing blank lines;
- remove indentation that is common to every non-blank line (YAML block indentation);
- remove trailing whitespace from each line.

It will not collapse interior spaces, alter blank-line count, change punctuation, case, wording, or template variables. YAML comments do not reach `prompt_template` after parsing and therefore do not require special handling. This narrowly treats source-formatting changes as equivalent while retaining any potentially semantic prompt edit.

## Selective invalidation and merge flow

For each existing score row, compare its saved metric content fingerprint and saved resolved model identity against the current configuration. Compare the saved metric-key set and each metric's saved evaluation group with the current definitions before comparing individual fingerprints.

1. If model provider or model identifier changed, mark every evaluation group stale.
2. Otherwise, mark a metric stale only when its saved content fingerprint differs from the current normalized content fingerprint, its prior refresh used a fallback, or is missing. Mark the prior and current group stale when a metric was added, removed, or moved.
3. Map stale metrics to their `evaluation_group`; this produces the groups that must be sent to the LLM again.
4. Re-run the LLM only for those groups, because group prompts include all metrics in that group and a single-metric request would no longer be comparable to historical grouped scoring.
5. Merge recalculated metric values for each stale group into the existing row. Preserve metric values for untouched groups and their existing score details.
6. Recompute group and overall status values from the merged metrics. Apply policy-only changes to every relevant metric without an LLM call.
7. Replace the row's `value_versions` with current per-metric fingerprints, current policy fingerprints, resolved model identity, composite fingerprint, group membership, and per-group refresh quality (`llm` or `heuristic_fallback`). A later run retries groups whose quality is `heuristic_fallback`.

New chat-history rows continue to evaluate all groups. Existing rows do not rely on the global composite fingerprint as the sole cache key; it remains an audit/version summary in state and output.

## State and compatibility

Retain `evaluation_fingerprint` and `policy_fingerprints` in state for run-level auditability and resume metadata. Add enough state or row-level comparison logic to avoid clearing all cached scores solely because the composite value changed. The score row is the source of truth for per-row validity, because mixed historical configurations are expected during a partial selective refresh.

If a legacy score row lacks `value_versions.metrics`, group membership, refresh quality, or resolved model identity, safely classify it as stale for all groups and overwrite it after evaluation. Do not attempt to infer old prompt content from its aggregate hash. When definitions remove metrics, remove their cached values before group statuses are recomputed; when they add or move metrics, regenerate every affected group.

## Error handling

When an affected group LLM call fails or returns invalid JSON, preserve the existing runner behavior for that group: use heuristic values for its refreshed metrics, record current versions and `heuristic_fallback` quality, and continue. A later monitoring run must retry that group even when its fingerprints are otherwise unchanged. Do not discard valid cached scores from unaffected groups.

## Tests

- Unit-test canonicalization: CRLF, YAML indentation, trailing whitespace, and outer blank lines produce equal content fingerprints; interior whitespace, punctuation, wording, and variables produce different fingerprints.
- Unit-test stale-group calculation for no changes, one safety metric, one performance metric, multiple groups, model change, and legacy rows.
- Unit-test partial group refresh: safety replacement preserves performance metrics, and vice versa; statuses and versions are recomputed from merged metrics.
- Unit-test added, removed, and moved metrics invalidate their affected groups and remove obsolete cached values.
- Unit-test model identity changes and heuristic-fallback refresh quality, including a subsequent successful retry.
- Integration-test a completed monitoring run followed by a one-metric change: only the affected group is called and unaffected group scores survive.
- Integration-test a formatting-only change: no score is sent for LLM re-evaluation.
- Keep the existing threshold-only no-LLM-re-evaluation coverage and revise any assertions that assume a prompt change clears every row.

## Out of scope

- Semantic similarity or LLM-based equivalence detection for prompts.
- Reorganizing metrics or changing group composition.
- Reusing results across model/deployment changes.
