# Governed continuous learning

ASE can improve its evaluator policies and synthetic evaluation assets over
time without changing the target chatbot, application code, or model weights.
Learning is a champion/challenger workflow: completed synthetic runs become
evidence, a bounded candidate is proposed, the candidate is evaluated against
the active bundle, and a human decides whether to activate it.

## Safety boundary

V1 accepts only completed, non-dry-run unified runs whose persisted contract and
run-plan fingerprints still match their artifacts. It rejects production or
non-synthetic rows. A candidate can:

- adjust bounded evaluation recipe weights;
- set attack-selection exploration policy;
- add or edit schema-valid personas and scenarios.

A candidate cannot change target configuration, LLM/provider configuration,
scoring, output paths, schedules, component overrides, or executable code.
Candidate generation never receives the locked validation contracts.

Learning can mine, propose, and evaluate automatically. It cannot activate a
candidate. `ase learn approve` is the only forward activation path, and it
requires an actor and reason. Approval uses the active bundle digest captured
when the candidate was created, so a stale decision cannot replace a newer
active bundle. Rollback also requires a recorded human actor and reason and can
target only a previously approved bundle.

## Profile configuration

Enable learning on a loop profile:

```yaml
learning:
  enabled: true
  evidence_source: synthetic_only
  min_new_runs: 3
  min_new_adversarial_conversations: 100
  candidate_kinds:
    - policy
    - persona
    - scenario
  validation_contracts:
    - contracts/examples/unified_evaluation_demo.yaml
  require_human_approval: true
  tournament:
    initial_pairs: 20
    batch_pairs: 20
    max_pairs: 100
  promotion:
    novelty_weight: 0.7
    coverage_weight: 0.3
    max_detection_drop_points: 5.0
    max_judge_error_increase_points: 1.0
    max_token_cost_increase_ratio: 0.2
```

`validation_contracts` is required when learning is enabled. The operator must
keep this pack independent from the evidence used for candidate generation.
V1 fixes `evidence_source` to `synthetic_only` and
`require_human_approval` to `true`.

An enabled live loop checks for learning eligibility after reflection. The
default trigger requires three newly mined runs and 100 adversarial
conversations. Dry-run loop cycles never launch a learning tournament.
Learning failures are recorded in loop state and the human inbox but do not
pause or invalidate the completed evaluation cycle.

## Operator workflow

Run or inspect a learning cycle:

```bash
PROFILE_ID=continuous_learning_evaluator
uv run ase learn run --profile "$PROFILE_ID"
uv run ase learn status --profile "$PROFILE_ID"
uv run ase learn show --profile "$PROFILE_ID" --candidate <candidate-id>
uv run ase learn audit --profile "$PROFILE_ID"
```

Record a decision:

```bash
uv run ase learn approve \
  --profile "$PROFILE_ID" \
  --candidate <candidate-id> \
  --actor <reviewer-id> \
  --reason "Novel failures reproduced without gate regressions"

uv run ase learn reject \
  --profile "$PROFILE_ID" \
  --candidate <candidate-id> \
  --actor <reviewer-id> \
  --reason "Coverage regression"

uv run ase learn rollback \
  --profile "$PROFILE_ID" \
  --to <previous-bundle-id> \
  --actor <reviewer-id> \
  --reason "Post-activation regression"
```

An approved bundle is resolved once at the next loop-run boundary. Its ID,
digest, parent, patch, and policy are included in `contract.normalized.json`
and therefore in the existing contract fingerprint. Resuming an incomplete run
with a different bundle is rejected by the normal v2 resume checks.

For a reproducible direct run, pass a bundle file or a bundle/candidate ID from
the default `outputs/learning/` tree:

```bash
uv run ase run \
  --contract contracts/examples/unified_evaluation_demo.yaml \
  --learning-bundle <bundle-id-or-path>
```

This explicit run-scoped override does not activate the bundle or change the
profile's active pointer. Normal loop runs consume only the human-approved
active bundle.

## Tournament and promotion

Champion and challenger use paired seeds and the same target fingerprint.
Validation begins with 20 pairs and expands in batches of 20, up to 100, while
evidence remains inconclusive. Half of each batch uses locked validation
contracts; half uses fresh exploration.

A structural failure signature contains target fingerprint, scenario type,
judge failure type, attack angle, and normalized sub-tactic. A signature is
reproducible only after appearing on at least two distinct paired seeds.
Promotion requires:

- at least one additional reproducible signature;
- a positive paired 95% confidence interval for the weighted score;
- no enabled taxonomy category loss;
- no locked-pack detection drop over 5 percentage points;
- no judge-error increase over 1 percentage point;
- no token-cost increase over 20 percent.

The weighted score is 70 percent fresh-seed novelty and 30 percent normalized
persona/scenario/angle coverage. A result still inconclusive at 100 pairs fails
closed.

## Artifacts

Artifacts are stored under `outputs/learning/<profile_id>/`:

- `experience.jsonl`: append-only, deduplicated run evidence;
- `candidates/<candidate_id>/bundle.json`: canonical governed bundle;
- `manifest.json`: immutable lineage and expected-active digest;
- `diff.jsonpatch`: reviewable evaluator-only patch;
- `evaluation.json` and `evidence.md`: tournament evidence;
- `decisions.jsonl`: append-only lifecycle and human decision events;
- `active.json`: atomically replaced active bundle pointer.

Run `ase learn audit` to verify bundle digests, manifest consistency, approval
history, and the active pointer.
