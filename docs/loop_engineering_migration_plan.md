# Loop Engineering Migration Plan for Adaptive Synth and Adversarial Agent Eval CLI

Date: 2026-06-10
Last Enhanced: 2026-06-15 (integrated loop engineering patterns + multi-provider LLM support)

## 1. Objective

Migrate the existing `ase` CLI from one-off contract execution to loop-based operation, where recurring control loops continuously:
- autonomously discover work and adapt evaluation strategy,
- run the right evaluation mode,
- verify outcomes and reflect on results,
- update durable state with learned insights,
- escalate only when human action is required.

Inspired by loop engineering best practices: loops prompt themselves, make decisions, generate follow-up actions, and iterate without human in the conversation loop. Supports pluggable LLM providers (Azure OpenAI, AWS Bedrock, Ollama, etc.).

Reference of loop egnineering: https://github.com/cobusgreyling/loop-engineering

This plan follows loop-engineering readiness levels:
- L0: Static contract loops (existing `ase run` automation)
- L1: Report-only loops with AI-driven discovery
- L2: Assisted loops (small, low-risk actions with verification)
- L3: Unattended loops (strict gates, budget caps, kill switches)

## 1b. LLM Provider Support

Loops are designed to work with multiple LLM providers to maximize flexibility:

- **Azure OpenAI**: Enterprise-grade, HIPAA-compliant, suitable for production deployments
  - Models: GPT-4 Turbo, GPT-4o (requires Azure subscription)
  - Cost: Variable per token
  - Latency: 1-3s typical
  - Setup: Requires `AZURE_OPENAI_KEY`, `AZURE_OPENAI_ENDPOINT`

- **AWS Bedrock**: AWS-native, supports multiple model vendors (Anthropic, Cohere, Meta, etc.)
  - Models: Claude 3, Cohere Command, Llama, Titan
  - Cost: Pay-per-token via AWS account
  - Latency: 1-3s typical
  - Setup: Requires AWS credentials with Bedrock access

- **Ollama**: Local, open-source, self-hosted
  - Models: Mistral, Llama 2/3, Phi, Neural Chat (runs locally)
  - Cost: Free (runs on your hardware)
  - Latency: 5-30s+ (depends on hardware, no GPU = very slow)
  - Setup: Run `ollama serve` locally, endpoint defaults to `http://localhost:11434`

- **Local Fallback**: Direct Python library if installed (e.g., `transformers` with Hugging Face model)
  - Cost: Free
  - Latency: 10-60s+ (CPU bound)
  - Setup: Download model, ensure library available

## 2. Current Baseline (What Already Exists)

The project already has several strong loop primitives:
- CLI orchestration entrypoint (`src/adaptive_synth_eval/cli.py`)
- Mode abstraction (`src/adaptive_synth_eval/evaluation/modes.py`) with `synth` and `unified`
- Durable run checkpointing and resume/restart (`src/adaptive_synth_eval/artifacts/run_state.py`)
- Progressive artifact output and run logs (`docs/output_artifacts.md`)
- Concurrency, retries, and budget controls in unified runner (`src/adaptive_synth_eval/unified_eval/orchestrator/runner.py`)
- Contract-driven behavior and weighted traffic plans (`contracts/examples/*.yaml`)

What is missing for full loop engineering:
- explicit scheduler/cadence layer for recurring execution
- loop state/memory file that spans many runs (not only single run checkpoints)
- maker/checker split at loop level
- first-class human handoff and escalation queue
- standardized risk gates and denylist for unattended actions
- loop budget policy and append-only loop run log (cross-run observability)

## 3. Target Loop Architecture

Introduce a loop layer above the current run engine.

### 3.1 New Components

1. Loop scheduler
- Trigger loops by cadence and optional event hooks.
- Support immediate run + recurring mode.

2. Loop state store
- Durable state per loop profile (JSON + markdown summary).
- Tracks backlog, last run status, retries, escalations, and human overrides.

3. Loop planner (Maker)
- Select next actions from state and fresh signals.
- Produces run intents (contract, mode, filters, dry-run/live).

4. Loop verifier (Checker)
- Independent verification pass on artifacts.
- Fails runs that violate policy thresholds, output completeness, or safety criteria.

5. Loop policy engine
- Human gates, denylist paths, retry limits, kill-switch handling.
- Enforces level-specific behavior (L1/L2/L3).

6. Loop observability
- `loop-budget.md` for daily/weekly token caps and thresholds.
- `loop-run-log.md` append-only run history.
- `STATE.md` loop-level status and open handoffs.

### 3.2 Data Flow

1. Scheduler triggers a loop profile.
2. Planner reads `STATE.md` + loop state JSON + recent run artifacts.
3. **AI-driven discovery**: Planner uses configured LLM (Azure/AWS/Ollama) to analyze prior results and autonomously decide next evaluation target.
4. Planner emits one or more run intents (custom or from contract library).
5. Existing `ase run` execution path runs unchanged (reuse current core).
6. Verifier validates outputs (`run_summary.json`, `scores.jsonl`, failures, checkpoints).
7. **Self-reflection**: Verifier uses configured LLM to analyze results and identify gaps, regressions, or areas needing deeper evaluation.
8. Policy engine decides: close, retry, escalate to human inbox, or trigger follow-up adaptive evaluation.
9. State and logs are persisted with AI-generated insights and recommendations.

## 3.3 AI-Driven Loop Reasoning (New Pattern)

Rather than static, human-written prompts, loops themselves generate adaptive prompts and iterate:

- **Self-Prompting**: Loop maintains a context window of prior evaluations, metrics, and findings, then prompts a configured LLM (Azure OpenAI, AWS Bedrock, Ollama, etc.) to decide: "What should we test next?"
- **Autonomous Decisions**: AI generates new evaluation targets, parameter combinations, or edge cases based on gap analysis.
- **Multi-Turn Reasoning**: Loop and LLM converse across multiple cycles. Previous run outcomes inform next cycle's hypothesis.
- **Self-Reflection**: After each evaluation, LLM analyzes results to identify failure patterns, unexpected behaviors, or promising areas to explore further.
- **Adaptive Denylist**: Dangerous test combinations or high-risk scenarios are flagged by the LLM, then confirmed by checker before allowed.

This shifts from "human writes contract → system executes → human reviews" to "loop runs → AI reasons → loop acts → loop reflects → AI refines → repeat."

### 3.4 Loop Reasoning Components

1. **Autonomous Planner (AI-Enhanced)**
   - Receives loop state, prior run summaries, and anomalies
   - Prompts configured LLM to generate next evaluation target + reasoning
   - Includes guard rails: allowed domains, forbidden combinations, risk scoring
   - Returns run intent with AI-generated hypothesis

2. **Self-Reflection Verifier**
   - Analyzes run outputs (metrics, logs, failures)
   - Prompts configured LLM: "What patterns do you see? What failed? What needs follow-up?"
   - Flags anomalies, regressions, or unexpected insights
   - Stores reflection in `loop-run-log.md` for cross-run learning

3. **Adaptive Policy Engine**
   - Enforces hard gates at L2/L3, but allows soft gates for L1 AI-driven discovery
   - Can veto unsafe recommendations from AI planner
   - Logs all AI reasoning and policy decisions for auditability

### 3.5 Storing AI Reasoning in Loop State

New fields in loop state JSON and `STATE.md`:

```json
{
  "loop_id": "daily_triage",
  "last_cycle": {
    "timestamp": "2026-06-15T10:30Z",
    "ai_reasoning": "Recent evaluation shows 15% increase in latency on TFSA end-to-end. Recommending focused profiling of serialization hot paths.",
    "ai_hypothesis": "Protocol buffer encoding is the bottleneck under high traffic.",
    "recommended_action": "Run unified_eval with 10k concurrent chat threads.",
    "checker_decision": "APPROVED with risk score 0.3 (low)",
    "outcome": {
      "run_status": "success",
      "key_finding": "Confirmed: 80% latency from RPC serialization.",
      "ai_reflection": "Hypothesis validated. Next: should test alternative codecs or caching layer.",
      "follow_up_enabled": true
    }
  }
}
```



## 4. Repository Changes (Planned)

## 4.1 New directories/files

```text
src/adaptive_synth_eval/loop/
  __init__.py
  scheduler.py
  profiles.py
  state_store.py              (Leverages atomic write-replace semantics of run_state.py)
  planner.py
  ai_planner.py              (NEW: AI-based autonomous discovery, utilizing existing LLMClient)
  verifier.py
  reflection_verifier.py      (NEW: AI-based self-reflection, utilizing existing LLMClient)
  policy.py
  observability.py
  runner.py
  reasoning_audit.py          (NEW: reasoning audit trail storage)

loops/                        (Checked into Git)
  profiles/
    daily_triage.yaml
    tfsa_weekly_health.yaml
    unified_regression_guard.yaml
  prompts/                    (NEW: AI reasoning prompt library)
    planner_discovery.txt
    reflection_analysis.txt
    hypothesis_generation.txt

outputs/loops/                (Gitignored - active runtime state and observability logs)
  STATE.md                    (Loop-level status and open handoffs)
  loop-budget.md              (Daily/weekly token caps and thresholds)
  loop-run-log.md             (Append-only run history)
  reasoning-audit.jsonl        (NEW: AI reasoning audit trail)
```

## 4.2 CLI extensions in `src/adaptive_synth_eval/cli.py`

Add subcommands:
- `ase loop init --profile <id>`
- `ase loop run --profile <id> [--once]`
- `ase loop start --profile <id>` (recurring scheduler)
- `ase loop status [--profile <id>]`
- `ase loop pause --profile <id>`
- `ase loop resume --profile <id>`
- `ase loop audit [--profile <id>]`

Keep existing commands unchanged:
- `validate-contract`
- `run`
- `summarize`

This preserves backward compatibility while adding loop operation as an optional top layer.

## 4.3 Contract/profile schema additions

Do not overload existing eval contracts initially. Add loop profiles under `loops/profiles/*.yaml`:
- `profile_id`
- `readiness_level` (`L1|L2|L3`)
- `cadence` (`cron` or interval)
- `targets` (contract path + optional filters)
- `max_iterations_per_cycle`
- `budget_policy_ref`
- `escalation_rules`
- `human_gates`
- `denylist`
- `checker_policy`
- `llm_config` (NEW - for AI reasoning):
  - `provider` (`azure_openai`, `bedrock`, `ollama`, `local`)
  - `model_name` (e.g., `gpt-4-turbo`, `anthropic.claude-3-sonnet`, `mistral`)
  - `endpoint_url` (for custom endpoints or Ollama)
  - `max_tokens_per_call` (safety limit)
  - `temperature` (0.0-1.0 for determinism vs. creativity)
  - `fallback_provider` (optional backup if primary fails)

Later optional step: allow referencing loop profile from unified contracts.

## 5. Rollout Plan by Readiness Level (Continuous Milestone-Based)

## Milestone 0: Foundation and Guardrails

Deliverables:
- Loop profile schema + parser + validation tests
- Persistent loop state store (leveraging atomic write-replace pattern from [run_state.py](./src/adaptive_synth_eval/artifacts/run_state.py))
- `STATE.md` generation utilities (writing to gitignored `outputs/loops/` directory)
- `loop-budget.md` and `loop-run-log.md` writers
- `ase loop init`, `ase loop status`

Acceptance criteria:
- Project can initialize loop assets with one command.
- State survives process restarts.
- No impact to current `ase run` behavior.

## Milestone 1: L1 Report-Only Loops with AI Discovery

Goal: AI autonomously discovers what to evaluate; zero autonomous code changes; triage/report only.

Loop behavior:
- Execute configured contracts in dry-run or safe run mode.
- **LLM-driven planner analyzes prior results and suggests next evaluation target** (why, what metrics matter, expected outcome).
- Summarize quality/safety signals, incomplete runs, budget trends, and AI-generated insights.
- **AI reflection**: After runs, LLM analyzes results and proposes follow-up hypotheses.
- Write recommendations and escalation items to `outputs/loops/STATE.md` with AI reasoning attached.

Deliverables:
- LLM-enhanced planner using the existing `LLMClient` (Azure OpenAI, AWS Bedrock, Ollama) for autonomous discovery
- Self-reflection verifier that analyzes outcomes and generates insights using the existing `LLMClient`
- Scheduler (`ase loop start --profile ...`)
- Updated verifier that captures AI reflection
- Human inbox section in `STATE.md` includes AI reasoning + human decision point

Acceptance criteria:
- Loop can run daily/hourly and produce high-signal reports with LLM-generated discovery rationale.
- AI reasoning is explainable and auditable (stored in state).
- No mutation beyond loop state/log files.
- False-positive escalations under agreed threshold.
- At least one LLM-discovered evaluation target per cycle that adds value beyond static contracts.

## Milestone 2: L2 Assisted Loops

Goal: allow constrained low-risk actions with checker approval.

Allowed actions (initial):
- Auto-resume incomplete run when safe (reusing the incomplete-run-action logic from [cli.py](./src/adaptive_synth_eval/cli.py))
- Auto-restart stale failed run with bounded retries
- Apply safe runtime overrides from policy (concurrency cap reductions)
- Regenerate summaries for missing artifacts

Required safeguards:
- maker/checker split enforced in code path
- max retry attempts per item
- denylist blocks risky target/scenario classes from auto-action
- all actions logged to `outputs/loops/loop-run-log.md`

Deliverables:
- Policy engine with risk classes
- Verifier hard-fail on checker rejection
- Loop audit command producing readiness report

Acceptance criteria:
- Assisted actions improve recovery time without increasing incident rate.
- Every assisted action is explainable from state + logs.

## Milestone 3: L3 Unattended Loops

Goal: trusted unattended operation with strict gates.

Capabilities:
- Fully recurring loops during configured windows
- Multi-profile coordination and priority ordering
- Automated pause on budget/safety breach
- Escalation-only notifications

Required controls:
- kill switch (`paused: true` in state or profile)
- daily token and run caps
- auto-pause on repeated checker failures
- explicit human gates for high-risk scenarios

Deliverables:
- Multi-loop coordinator
- Priority scheduler and backoff strategy
- production runbooks in docs

Acceptance criteria:
- Loops run unattended for pilot period with no policy violations.
- Human intervention is exception-driven, not run-by-run.

## 6. Detailed Implementation Backlog

## Workstream A: Loop framework

1. Build loop profile schemas and validation.
2. Implement `state_store.py` with atomic writes and recovery.
3. Implement scheduler abstraction (interval + cron).
4. Add `runner.py` that bridges planner -> existing `ase run` -> verifier.
5. Add CLI wiring for `loop` command group.

## Workstream A+: AI-Driven Loop Reasoning (New)

1. **Reuse and Adapt LLMClient** (FIRST PRIORITY - MAPPED TO CODEBASE)
   - Reuse `adaptive_synth_eval.clients.llm.LLMClient` instead of building a new client from scratch.
   - `LLMClient` already abstracts Azure OpenAI, AWS Bedrock, Anthropic, OpenAI, and Ollama using LangChain.
   - Refactor or extend `LLMClient` as necessary to support loop reasoning prompt templates (discovery, reflection, hypothesis) and fallback settings.
   - Route all AI reasoning calls through this client for consistency.

2. **Autonomous Planner with LLM Integration**
   - Implement `ai_planner.py` that calls configured LLM with context (prior runs, metrics, anomalies).
   - LLM generates next evaluation target with reasoning.
   - Return structured run intent including hypothesis and risk score.
   - Add configurable prompt template for different loop types (triage, regression, exploratory).

3. **Self-Reflection Verifier**
   - Extend `verifier.py` to accept configured LLM client.
   - After run completes, prompt LLM: analyze outputs, identify patterns, propose follow-ups.
   - Store reflection blob in loop state under `last_cycle.ai_reflection`.
   - Grade reflection quality: is it actionable? Does it match actual findings?

4. **Loop Reasoning Guardrails**
   - Implement denylist + allowlist for LLM-generated targets (e.g., approved contract families, forbidden parameter ranges).
   - Risk scoring: flag high-risk combinations for human review even at L1.
   - Token budget: track LLM calls and token spend per cycle to avoid runaway reasoning.

5. **Reasoning Audit Trail**
   - Store all LLM prompts + responses in structured logs.
   - Make reasoning visible in `loops/STATE.md` for transparency.
   - Support replaying LLM reasoning for offline analysis.

## Workstream B: Maker/Checker split

1. Planner generates run intents and expected outcomes.
2. Verifier validates artifacts and applies policy thresholds.
3. Store checker verdicts in loop state.
4. Block completion without checker pass in L2/L3.

## Workstream C: Observability and budgets

1. Standardize loop run record format.
2. Implement budget tracker over unified run summaries.
3. Add budget breach triggers and auto-pause logic.
4. Add readiness audit scoring (L0-L3 rubric aligned).

## Workstream D: Human handoff

1. Define escalation object schema.
2. Add human inbox section to `loops/STATE.md`.
3. Add acknowledgement/override flow in state.
4. Add optional connector interface (future: Jira/Slack/GitHub).

## 7. Test Strategy

Unit tests:
- profile parsing and validation
- state-store atomicity and corruption recovery
- planner decision logic
- policy denylist and escalation rules
- verifier pass/fail behavior

**AI Reasoning Tests (New)**:
- Mock LLM API responses: verify LLM planner correctly parses discovery recommendations
- Verify risk scoring: high-risk targets flagged, low-risk approved
- Reflection quality: self-reflection identifies anomalies that humans would catch
- Denylist enforcement: LLM recommendations violating guardrails are blocked
- Token budget tracking: verify LLM call counts and token spend stay within limits
- Multi-provider compatibility: verify abstraction layer works with Azure, AWS, Ollama

Integration tests:
- `ase loop init/status/run` command flows
- scheduler once-mode and recurring-mode execution
- L1 report-only run producing state and logs
- L1 AI discovery: planner suggests valid evaluation, reflection is generated
- L2 assisted recovery on incomplete runs
- kill-switch pause/resume behavior
- End-to-end LLM loop cycle: discovery -> run -> reflection -> next cycle hypothesis
- Multi-provider fallback: verify loop switches gracefully if primary LLM provider is unavailable

Non-functional tests:
- long-running stability (24h loop soak)
- cost guardrail tests with synthetic token budgets (including LLM token spend)
- restart/recovery tests across process interruption
- AI reasoning latency: planner + reflection should not add >30s per cycle
- LLM provider latency: verify response times for Azure/AWS/Ollama within acceptable bounds

## 8. Risk Register and Mitigations

1. Loop thrash (repeating same failing action)
- Mitigation: max-attempts, exponential backoff, checker hard block.

2. Budget runaway
- Mitigation: daily cap, per-cycle cap, reserve threshold, auto-pause.

3. Silent failure due to stale state
- Mitigation: state versioning, migration guard, periodic consistency checks.

4. Over-notification fatigue
- Mitigation: notify only on escalation-required transitions.

5. Unsafe autonomous behavior
- Mitigation: L1 first, L2 constraints, L3 only after readiness audit passes.

6. **AI Hallucination**: Claude generates invalid or unsafe evaluation targets
- Mitigation: strict schema validation on AI output, denylist/allowlist gates, human review of high-risk recommendations, use of structured prompt with examples.

7. **AI Token Runaway**: AI reasoning LLM calls consume all budget
- Mitigation: separate LLM token budget from evaluation token budget, per-cycle call limit (e.g., max 3 planner + 3 reflection calls/cycle), monitor and alert on spend trends.

8. **Reasoning Drift**: AI's hypotheses diverge from true system behavior
- Mitigation: regular ground-truth validation (compare AI reflection with actual findings), human audit of AI reasoning quarterly, fallback to L1 if drift detected.

9. **Compounding Errors**: AI bases next hypothesis on flawed prior reflection
- Mitigation: verifier explicitly validates prior reflection, reset reasoning context if contradiction found, enforce human gate on hypothesis chains >3 cycles deep.

## 9. Suggested Initial Loop Profiles for This Repo

1. `daily_triage` (L1)
- Cadence: weekday daily
- Scope: summarize latest run health, incomplete runs, quality drift
- Action: report only

2. `tfsa_weekly_health` (L1 -> L2)
- Cadence: every 6 hours
- Scope: TFSA contracts, throughput/safety trend check
- Action at L2: auto-resume interrupted runs only

3. `unified_regression_guard` (L2)
- Cadence: on-demand or every 2 hours
- Scope: focused unified contract sanity run
- Action: bounded restart + summary regeneration

## 9a. Example Loop Profile Configurations (Multi-Provider)

### Example 1: Azure OpenAI (Production, High Quality)

```yaml
profile_id: daily_triage_azure
readiness_level: L1
cadence: "0 8 * * MON-FRI"  # 8 AM weekdays
targets:
  - contract: contracts/examples/chatbot_test_contract.yaml
llm_config:
  provider: azure_openai
  model_name: gpt-4-turbo
  endpoint_url: "${AZURE_OPENAI_ENDPOINT}"  # From env
  max_tokens_per_call: 2000
  temperature: 0.3  # Low = deterministic reasoning
```

### Example 2: AWS Bedrock (Cost-Effective, Multi-Model)

```yaml
profile_id: tfsa_weekly_bedrock
readiness_level: L1
cadence: "0 */6 * * *"  # Every 6 hours
targets:
  - contract: contracts/examples/tfsa_assistant.yaml
llm_config:
  provider: bedrock
  model_name: anthropic.claude-3-sonnet-20240229-v1:0
  max_tokens_per_call: 1500
  temperature: 0.5
  fallback_provider: ollama  # If Bedrock fails, try local Ollama
```

### Example 3: Ollama (Local, Privacy-First)

```yaml
profile_id: regression_guard_ollama
readiness_level: L2
cadence: "*/2 * * * *"  # Every 2 hours
targets:
  - contract: contracts/examples/unified_evaluation_demo.yaml
llm_config:
  provider: ollama
  model_name: mistral:latest
  endpoint_url: http://localhost:11434
  max_tokens_per_call: 1000
  temperature: 0.4
```

### Example 4: Fallback Strategy (Resilient to Provider Outages)

```yaml
profile_id: critical_loop_resilient
readiness_level: L2
cadence: "0 * * * *"  # Hourly
targets:
  - contract: contracts/examples/browser_chatbot_test.yaml
llm_config:
  provider: azure_openai
  model_name: gpt-4-turbo
  endpoint_url: "${AZURE_OPENAI_ENDPOINT}"
  max_tokens_per_call: 2000
  fallback_provider: bedrock  # Try AWS Bedrock if Azure fails
  fallback_model_name: anthropic.claude-3-sonnet-20240229-v1:0
```

## 10. Continuous Migration Sequence (Step-by-Step)

Migration should proceed sequentially from foundational features to higher autonomy, validating each milestone before proceeding:

- **Step 1**: Implement Milestone 0 (foundation, configuration parse, and state store) and CLI scaffolding.
- **Step 2**: Roll out Milestone 1 (report-only loops with L1 AI discovery) for a test profile.
- **Step 3**: Introduce Milestone 2 (assisted actions with checker verification + AI reflection).
- **Step 4**: Transition to Milestone 3 (unattended operation with strict budget guardrails and automated kill switches).

## 10a. Step-by-Step AI Reasoning Integration

To minimize risk, introduce AI reasoning incrementally:

1. **L1a (Milestone 1 - Planning)**: AI planner suggests next evaluation; human reviews in `STATE.md` before any action is executed.
2. **L1b (Milestone 1 - Reflection)**: AI reflection is generated after runs; human reviews insights, but no automated action is taken.
3. **L2a (Milestone 2 - Execution)**: AI-recommended recovery actions flow to the checker; checker approves or blocks based on safety rules and logs details in the audit trail.
4. **L3 (Milestone 3 - Autonomy)**: AI reasoning loops run autonomously, managed by hard gates, daily caps, and automated kill switches.

**Gate to L2**: Verify AI discovery quality over 10+ cycles (do its recommendations add signal? do they match human intuition?).

**Gate to L3**: Verify AI reasoning has <2% unsafe recommendations over 100+ cycles; establish baseline for "drift detection".

## 10b. AI Reasoning Best Practices

1. **Prompt Engineering**: Maintain library of proven loop prompts (discovery, reflection, hypothesis-generation). Version and A/B test across different LLM providers.
2. **Context Window**: Keep state summaries within token limits of chosen LLM (e.g., <4k tokens for Azure/AWS smaller models, <20k for larger) so AI reasoning fits comfortably alongside conversation history.
3. **Model Selection**: Choose LLM provider/model based on:
   - Cost vs. quality tradeoff (Ollama local=free but lower quality; Azure/AWS=higher quality, higher cost)
   - Latency requirements (local Ollama <5s; cloud APIs 1-3s)
   - Privacy constraints (local Ollama stays on-device; cloud APIs may log)
4. **Grounding**: Include factual metrics (last 5 run scores, known constraints) in LLM planner context to reduce hallucinations.
5. **Explainability**: Store full LLM reasoning chain (prompt + response) so humans can understand why loop made a decision.
6. **Feedback Loop**: Quarterly review of LLM reasoning quality vs. human ground truth; if drift >5%, retrain prompt, switch model, or reduce autonomy level.

## 11. Definition of Done

Migration is complete when:
- loop commands are production-ready and documented,
- at least one L1 and one L2 profile run reliably,
- state/budget/run-log artifacts provide full run traceability,
- maker/checker split is enforced for assisted/unattended actions,
- readiness audit for targeted profiles meets required level,
- existing non-loop CLI workflows remain backward compatible,
- **AI-driven loop reasoning**: at least one loop profile uses LLM-based (Azure OpenAI / AWS Bedrock / Ollama) discovery and reflection at L1, with <5% false-positive rate over 20+ cycles,
- **AI reasoning auditability**: full reasoning chain (prompts, responses, decisions) is logged and reviewable,
- **LLM budget safeguards**: separate token budget for AI reasoning, per-cycle call limits enforced, token spend tracked in loop-budget.md, provider fallback configured for resilience.
