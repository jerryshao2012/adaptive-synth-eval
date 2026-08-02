# One-Day Time-Profile Verification

This guide verifies the schema-v3 Agent Skills profile example from contract
loading through monitoring and the dashboard. Run every command from the
repository root unless a step explicitly changes directories.

Repository-relative command paths use `/`. PowerShell, Windows Python,
macOS, and Linux all accept this separator. Generated absolute paths use each
shell's native path-join operation rather than concatenating `\\` or `/`.

The contract models three windows on one synthetic workday:

1. `morning_regular` — default behavior and context-building recipes.
2. `midday_busy` — higher traffic weight and stressed behavior.
3. `afternoon_toxicity_drill` — toxic behavior with an adversarial-heavy
   toxicity recipe.

These are synthetic clock labels, not wall-clock appointments. ASE plans all
three phases and executes them in the same command; it does not wait until
09:00, noon, or 15:00, and it does not sleep for
`compressed_runtime_minutes`. The complete structural check fits comfortably
within one company-laptop session.

## Windows PowerShell

Run this section in PowerShell from the repository root. It covers contract
validation, the complete one-day dry-run, artifact path checks, monitoring, and
dashboard startup without relying on Bash, `jq`, `find`, or `/tmp`.

Install dependencies and create `src/.env` only when it is missing:

```powershell
uv sync
if (-not (Test-Path -LiteralPath "src/.env")) {
    Copy-Item -LiteralPath "src/.env.example" -Destination "src/.env"
}
```

Create the run paths with `Join-Path`. The contract path deliberately uses
forward slashes because the same literal also works on macOS and Linux:

```powershell
$Contract = "contracts/examples/unified_agent_skills_time_profile_demo.yaml"
$OutputDir = Join-Path -Path (Get-Location).Path -ChildPath "outputs"
$env:ASE_TIME_PROFILE_OUTPUT_DIR = $OutputDir
$RunId = "agent-skills-profile-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
$RunsDir = Join-Path -Path $OutputDir -ChildPath "runs"
$RunDir = Join-Path -Path $RunsDir -ChildPath $RunId
```

Validate and execute all three synthetic phases immediately:

```powershell
uv run ase validate-contract "$Contract"
uv run ase run --contract "$Contract" --dry-run --run-id "$RunId"
```

Confirm the expected directory and artifacts:

```powershell
Write-Host "Run ID: $RunId"
Write-Host "Run directory: $RunDir"
Get-ChildItem -LiteralPath $RunDir -File | Sort-Object Name | Select-Object Name, FullName

$RequiredArtifacts = @(
    "contract.normalized.json",
    "run_plan.json",
    "run_state.json",
    "run_summary.json",
    "chat_history.jsonl",
    "turns.jsonl",
    "scores.jsonl"
)
foreach ($Name in $RequiredArtifacts) {
    $ArtifactPath = Join-Path -Path $RunDir -ChildPath $Name
    if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
        throw "Missing artifact: $ArtifactPath"
    }
}
```

Check the ordered one-day plan and show the traffic allocation by phase:

```powershell
$PlanPath = Join-Path -Path $RunDir -ChildPath "run_plan.json"
$Plan = @(Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json)
if ($Plan.Count -ne 12) { throw "Expected 12 conversations; found $($Plan.Count)" }

$ExpectedPeriods = @("morning_regular", "midday_busy", "afternoon_toxicity_drill")
$ActualPeriods = @($Plan | Select-Object -ExpandProperty profile_period_id -Unique)
if (($ActualPeriods -join "|") -ne ($ExpectedPeriods -join "|")) {
    throw "Unexpected profile periods: $($ActualPeriods -join ', ')"
}

$Plan |
    Group-Object profile_period_id |
    Select-Object Name, Count |
    Format-Table -AutoSize
```

Run monitoring and verify every score retains a simulation-period identifier:

```powershell
uv run ase monitor run --run-folder "$RunDir" --dry-run --sampling-strategy all --interval-minutes 60 --incomplete-run-action restart

$ScoresPath = Join-Path -Path $RunDir -ChildPath "monitoring_scores.jsonl"
$Scores = @(
    Get-Content -LiteralPath $ScoresPath |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_ | ConvertFrom-Json }
)
if ($Scores.Count -eq 0) { throw "No monitoring scores found at $ScoresPath" }
$MissingPeriod = @($Scores | Where-Object { -not $_.profile_period_id })
if ($MissingPeriod.Count -gt 0) {
    throw "$($MissingPeriod.Count) monitoring rows lack profile_period_id"
}

$Scores |
    Group-Object profile_period_id |
    Select-Object Name, Count |
    Format-Table -AutoSize
```

In a second PowerShell terminal, start the dashboard:

```powershell
Set-Location -LiteralPath "ai-eval-dashboard"
yarn install
yarn dev
```

Open [http://localhost:3000/monitor](http://localhost:3000/monitor), select the
value printed in `$RunId`, and confirm all three phase bands and comparison rows
are present.

## macOS/Linux

The remaining detailed workflow uses Bash or zsh. It performs the same core
run and monitoring checks plus deeper `jq` inspection and an optional isolated
resume/fingerprint smoke test.

## 1. Prepare the repository

Install Python dependencies and create the optional environment file without
overwriting an existing one:

```bash
uv sync
if [ ! -f src/.env ]; then cp src/.env.example src/.env; fi
```

The dry-run below does not need provider secrets. Unified dry-run forces the
harness LLM components to deterministic mock providers and disables real target
calls. Credentials in `src/.env` are needed only for a later live run.

Set stable shell variables. An explicit run ID makes the output location known
without parsing log text, while the timestamp prevents collisions:

```bash
CONTRACT=contracts/examples/unified_agent_skills_time_profile_demo.yaml
export ASE_TIME_PROFILE_OUTPUT_DIR="$PWD/outputs"
RUN_ID="agent-skills-profile-$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$ASE_TIME_PROFILE_OUTPUT_DIR/runs/$RUN_ID"
```

## 2. Validate and dry-run

Validate through the same public mode detection and loader used by the CLI:

```bash
uv run ase validate-contract "$CONTRACT"
```

Run the complete morning-to-afternoon simulation:

```bash
uv run ase run \
  --contract "$CONTRACT" \
  --dry-run \
  --run-id "$RUN_ID"
```

The final line prints `Run complete: <run_id>`. Confirm the expected output
directory and primary artifacts:

```bash
printf 'Run ID: %s\nRun directory: %s\n' "$RUN_ID" "$RUN_DIR"
find "$RUN_DIR" -maxdepth 1 -type f -print | sort
```

Expected files include `contract.normalized.json`, `run_plan.json`,
`run_state.json`, `run_summary.json`, `chat_history.jsonl`, `turns.jsonl`, and
`scores.jsonl`.

## 3. Inspect the normalized schema-v3 contract

With `jq`:

```bash
jq '{
  schema_version,
  suite_id: .suite.suite_id,
  synthetic_days: .time_window.num_synthetic_days,
  total_conversations: .eval_plan.total_conversations,
  agent_skills: .attack_skills,
  windows: .time_profile.windows
}' "$RUN_DIR/contract.normalized.json"
```

Check the essential invariants automatically:

```bash
uv run python - "$RUN_DIR/contract.normalized.json" <<'PY'
import json
import sys

contract = json.load(open(sys.argv[1], encoding="utf-8"))
assert contract["schema_version"] == 3
assert contract["time_window"]["num_synthetic_days"] == 1
assert contract["attack_skills"]["enabled"] is True
windows = contract["time_profile"]["windows"]
assert [w["period_id"] for w in windows] == [
    "morning_regular",
    "midday_busy",
    "afternoon_toxicity_drill",
]
assert [w["behavior_mode"] for w in windows] == ["default", "stressed", "toxic"]
recipes = {entry["recipe_id"] for entry in contract["eval_plan"]["entries"]}
assert len(recipes) == len(contract["eval_plan"]["entries"]) == 6
assert all(set(w["recipe_weights"]) <= recipes for w in windows)
print("normalized contract: schema v3, Agent Skills enabled, 3 ordered one-day windows")
PY
```

## 4. Verify plan order, counts, timestamps, and recipes

Show one compact row per planned conversation:

```bash
jq '.[] | {
  sequence,
  synthetic_timestamp,
  synthetic_slot,
  profile_period_id,
  profile_period_instance_id,
  recipe_id,
  persona_id,
  synth_scenario_id,
  adversarial_scenario_id,
  conversation_mode,
  behavior_mode
}' "$RUN_DIR/run_plan.json"
```

Summarize daily period instances in chronological order:

```bash
jq 'group_by(.profile_period_instance_id)
  | map({
      instance: .[0].profile_period_instance_id,
      period: .[0].profile_period_id,
      start: .[0].profile_period_start,
      end: .[0].profile_period_end,
      planned_conversations: length,
      recipes: (map(.recipe_id) | unique)
    })
  | sort_by(.start)' "$RUN_DIR/run_plan.json"
```

Use this Python fallback for assertions that are awkward to express in `jq`:

```bash
uv run python - "$RUN_DIR/run_plan.json" <<'PY'
from collections import Counter
from datetime import datetime
import json
import sys

plan = json.load(open(sys.argv[1], encoding="utf-8"))
assert len(plan) == 12
assert [row["sequence"] for row in plan] == list(range(1, 13))
timestamps = [datetime.fromisoformat(row["synthetic_timestamp"]) for row in plan]
assert timestamps == sorted(timestamps)
required = {
    "recipe_id", "synthetic_timestamp", "synthetic_slot",
    "profile_period_id", "profile_period_instance_id",
    "profile_period_start", "profile_period_end",
    "conversation_mode", "behavior_mode", "traffic_weight", "recipe_weights",
}
assert all(required <= row.keys() for row in plan)
counts = Counter(row["profile_period_id"] for row in plan)
assert set(counts) == {
    "morning_regular", "midday_busy", "afternoon_toxicity_drill"
}
assert all(count > 0 for count in counts.values())
print("plan counts:", dict(counts))
print("first/last timestamps:", timestamps[0].isoformat(), timestamps[-1].isoformat())
PY
```

The periods must remain in morning, midday, afternoon order. Higher traffic
weights usually allocate more of the remaining finite conversations to later
phases, but every phase is guaranteed at least one conversation.

## 5. Verify chat-history provenance and active recipes

Preview profile fields on the emitted turns:

```bash
jq -c '{
  conversation_id,
  turn_id,
  timestamp,
  synthetic_timestamp,
  profile_period_id,
  profile_period_instance_id,
  recipe_id,
  behavior_mode
}' "$RUN_DIR/chat_history.jsonl" | head -n 12
```

Verify required provenance, monotonic timestamps, and phase-active recipes:

```bash
uv run python - \
  "$RUN_DIR/contract.normalized.json" \
  "$RUN_DIR/chat_history.jsonl" <<'PY'
from collections import defaultdict
from datetime import datetime
import json
import sys

contract = json.load(open(sys.argv[1], encoding="utf-8"))
rows = [json.loads(line) for line in open(sys.argv[2], encoding="utf-8") if line.strip()]
active = {
    window["period_id"]: {
        recipe_id for recipe_id, weight in window["recipe_weights"].items() if weight > 0
    }
    for window in contract["time_profile"]["windows"]
}
required = {
    "timestamp", "synthetic_timestamp", "recipe_id", "synthetic_slot",
    "profile_period_id", "profile_period_instance_id",
    "profile_period_start", "profile_period_end",
    "conversation_mode", "behavior_mode", "traffic_weight", "recipe_weights",
}
assert rows and all(required <= row.keys() for row in rows)
assert all(row["recipe_id"] in active[row["profile_period_id"]] for row in rows)
by_conversation = defaultdict(list)
for row in rows:
    by_conversation[row["conversation_id"]].append(datetime.fromisoformat(row["timestamp"]))
assert all(values == sorted(values) for values in by_conversation.values())
period_order = {"morning_regular": 0, "midday_busy": 1, "afternoon_toxicity_drill": 2}
observed = [period_order[row["profile_period_id"]] for row in rows]
assert observed == sorted(observed)
print(f"chat history: {len(rows)} turns across {len(by_conversation)} conversations")
PY
```

## 6. Run deterministic post-hoc monitoring

Evaluate every existing chat row locally. Monitoring scores artifacts; it does
not generate conversations or schedule profile windows.

```bash
uv run ase monitor run \
  --run-folder "$RUN_DIR" \
  --dry-run \
  --sampling-strategy all \
  --interval-minutes 60 \
  --incomplete-run-action restart
```

Preview phase provenance on monitoring rows:

```bash
jq -c '{
  timestamp,
  conversation_id,
  turn_id,
  recipe_id,
  profile_period_id,
  profile_period_instance_id,
  behavior_mode,
  sample_window_id,
  safety_status,
  performance_status
}' "$RUN_DIR/monitoring_scores.jsonl" | head -n 12
```

Verify that profile provenance was copied and that `sample_window_id` remains a
separate monitoring-processing window number:

```bash
uv run python - \
  "$RUN_DIR/chat_history.jsonl" \
  "$RUN_DIR/monitoring_scores.jsonl" <<'PY'
import json
import sys

chat = {
    (str(row["conversation_id"]), str(row["turn_id"])): row
    for row in (json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip())
}
scores = [json.loads(line) for line in open(sys.argv[2], encoding="utf-8") if line.strip()]
copied = (
    "timestamp", "recipe_id", "profile_period_id", "profile_period_instance_id",
    "profile_period_start", "profile_period_end", "conversation_mode",
    "behavior_mode", "synthetic_slot", "synthetic_day", "scenario_id", "persona_id",
)
assert scores
for score in scores:
    source = chat[(str(score["conversation_id"]), str(score["turn_id"]))]
    assert all(score.get(field) == source.get(field) for field in copied)
    assert isinstance(score["sample_window_id"], int)
    assert score["sample_window_id"] != score["profile_period_id"]
print("monitoring rows preserve profile provenance; sample_window_id is independent")
PY
```

`profile_period_id` identifies the simulated morning/midday/afternoon phase.
`sample_window_id` only identifies an `ase monitor` processing bucket created by
`--interval-minutes`; it is not a simulation phase.

## 7. Verify the dashboard

The dashboard reads `outputs/runs`, which matches the output directory exported
in step 1. In a second terminal, from the repository root:

```bash
cd ai-eval-dashboard
yarn install
yarn dev
```

Open [http://localhost:3000/monitor](http://localhost:3000/monitor), select
`$RUN_ID`, and verify:

- **Dashboard period** defaults to **Full Run** for this profiled run.
- **Phase comparison** contains `morning_regular`, `midday_busy`, and
  `afternoon_toxicity_drill`, with each phase's modes, hours, counts, pass/fail,
  toxicity safety, safety average, and performance average.
- Metric charts show labeled shaded bands for the three ordered phase instances.
- Selecting Full Run keeps all same-day synthetic phases visible; chart-specific
  selectors can still narrow individual charts.

The mock target and deterministic dry-run judge prove structure, propagation,
and rendering. They do not prove that real toxicity scores worsen in the
afternoon. Meaningful phase-to-phase toxicity metric shifts require a live
target and a supported real monitoring judge; configure credentials, omit
`--dry-run`, and use a new run ID for that experiment.

## 8. Safe resume/fingerprint rejection smoke test

Use an isolated temporary output and copied contract. This leaves the checked-in
example and the dashboard run untouched:

```bash
SMOKE_DIR="$(mktemp -d)"
SMOKE_CONTRACT="$SMOKE_DIR/profile.yaml"
SMOKE_OUTPUT="$SMOKE_DIR/output"
SMOKE_RUN_ID=profile-fingerprint-smoke
cp "$CONTRACT" "$SMOKE_CONTRACT"
ASE_TIME_PROFILE_OUTPUT_DIR="$SMOKE_OUTPUT" uv run ase run \
  --contract "$SMOKE_CONTRACT" \
  --dry-run \
  --run-id "$SMOKE_RUN_ID"
```

Mark only the temporary completed checkpoint as incomplete so the CLI enters
the resume path:

```bash
jq '.status = "incomplete"' \
  "$SMOKE_OUTPUT/runs/$SMOKE_RUN_ID/run_state.json" \
  > "$SMOKE_DIR/run_state.json"
mv "$SMOKE_DIR/run_state.json" \
  "$SMOKE_OUTPUT/runs/$SMOKE_RUN_ID/run_state.json"
```

Change one fingerprinted value in only the temporary contract:

```bash
uv run python - "$SMOKE_CONTRACT" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = "reserve_tokens: 1500"
assert old in text
path.write_text(text.replace(old, "reserve_tokens: 1501", 1), encoding="utf-8")
PY
```

The following command must exit nonzero with `Cannot resume: the effective
contract differs from the run-state checkpoint.`:

```bash
ASE_TIME_PROFILE_OUTPUT_DIR="$SMOKE_OUTPUT" uv run ase run \
  --contract "$SMOKE_CONTRACT" \
  --dry-run \
  --run-id "$SMOKE_RUN_ID" \
  --incomplete-run-action resume
```

Inspect `$SMOKE_DIR` if desired, then remove that exact temporary directory when
finished. Do not point cleanup commands at the repository or `outputs/` root.

This smoke test covers contract fingerprint rejection. Changing recipe filters,
weights, the seed, or profile windows can also change the ordered plan and is
protected by the separate run-plan fingerprint.
