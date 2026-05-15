# Synthetic HR Chat Simulation CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python CLI that generates realistic, multi-turn synthetic ChatHistory data for a BMO HR policy chatbot without relying on production telemetry, Azure AI Evaluation Simulator, chatbot tool calls, or dashboard telemetry ingestion.

**Architecture:** Keep the CLI as the product surface. A JSON/YAML simulation contract drives personas, scenarios, traffic shape, synthetic days, variability, and output settings. The CLI generates user turns, calls the chatbot endpoint when configured, scores responses locally where possible, and writes reviewable ChatHistory and run-summary artifacts.

**Tech Stack:** Python, pytest, JSON/YAML contracts, HTTP chatbot API wrapper, local artifact exporters, existing `goldenQA` assets, and selected `deep_research` golden-dataset patterns for grounded question generation and quality scoring.

---

## 1. Active Scope

This plan implements the core of the Jira ticket with the updated project constraints:

- Keep a local Python CLI.
- Generate synthetic HR chatbot conversations without production telemetry.
- Do not use Azure AI Evaluation Simulator.
- Do not require observability/dashboard telemetry output.
- Do not assume chatbot tool calls exist.
- Generate ChatHistory data for one week at 30 users per hour across at least two profiles.
- Demonstrate that the framework can scale to at least 10,000 synthetic conversations.
- Support multi-turn conversations of 3-8 turns.
- Support personas, scenarios, weighted traffic mix, synthetic-day distribution, burst patterns, and controlled failure injection.

The primary deliverable is a packaged CLI and generated ChatHistory artifacts that the Evals team can run locally from their laptop.

---

## 2. Deep Agent Demo Applicability

### Use Now: `deep_research` Golden Dataset Pattern

Use the `deep_research` golden-dataset pattern as a reference for grounded Q/A generation and quality scoring.

The useful ideas are:

- Ground each generated question in internal policy context.
- Carry supporting context alongside every generated Q/A item.
- Track quality metrics such as groundedness, relevance, coherence, and similarity where local judging is available.
- Keep outputs easy to review and export.

### Backlog: `better-harness`

`better-harness` is still relevant later, but it is not part of the active Jira delivery. It should move to backlog as an optional future optimization layer for prompts, scoring, and failure-injection strategies once the CLI and ChatHistory generation path are stable.

---

## 3. Target Repository Structure

Create a package-style CLI while preserving existing scripts until they are safely wrapped.

```text
adaptive-synth-eval/
  IMPLEMENTATION_PLAN.md
  pyproject.toml
  src/
    adaptive_synth_eval/
      __init__.py
      cli.py
      config/
        contract.py
        schemas.py
      clients/
        chatbot.py
        llm.py
      engines/
        chat_history_simulation.py
      generation/
        personas.py
        scenarios.py
        traffic.py
        variability.py
        turns.py
      scoring/
        response_quality.py
        failure_modes.py
      artifacts/
        exporters.py
        schemas.py
  tests/
    unit/
    integration/
  contracts/
    examples/
      one_week_chat_history.yaml
      ten_k_conversations.yaml
  outputs/
    .gitkeep
```

Existing folders should be migrated gradually:

- `goldenQA/` remains the source for GoldenQA logic until wrapped by `generation/scenarios.py` or `scoring/response_quality.py`.
- `adverserial agent/` is not active scope for this Jira. Keep it available as reference material for future boundary-testing work only.

---

## 4. CLI Commands

The CLI must accept JSON or YAML contracts as the single source of truth.

Example commands:

```bash
uv run adaptive-synth-eval validate-contract contracts/examples/one_week_chat_history.yaml
uv run adaptive-synth-eval run --contract contracts/examples/one_week_chat_history.yaml
uv run adaptive-synth-eval run --contract contracts/examples/ten_k_conversations.yaml
uv run adaptive-synth-eval summarize --run-id <run_id>
```

The CLI should also support dry-run generation without calling the chatbot:

```bash
uv run adaptive-synth-eval run --contract contracts/examples/one_week_chat_history.yaml --dry-run
```

Dry-run mode should generate planned conversations and user turns, mark chatbot responses as omitted or mocked, and still write run artifacts for review.

---

## 5. Simulation Contract

The contract defines all behavior. Do not hardcode personas, scenarios, traffic weights, failure probabilities, or endpoints in code.

Required top-level sections:

```yaml
simulation_suite:
  suite_id: hr_policy_bot_synthetic_monitoring_v1
  target_application: internal_hr_policy_rag_bot
  run_mode: synthetic_chat_history_generation
  synthetic_flag: true

target_chatbot:
  endpoint: https://example.invalid/chat
  auth:
    type: bearer
    env_var: HR_CHATBOT_API_KEY
  enabled: true

time_window:
  start_day: "2026-05-01"
  num_synthetic_days: 7
  compressed_runtime_minutes: 60

persona_pool: []
scenario_catalog: []
traffic_orchestration: {}
output: {}
```

### Persona Schema

Each persona must include:

- `persona_id`
- `role`
- `location`
- `seniority`
- `communication_style`
- `hr_familiarity`
- `privacy_sensitivity`

Optional persona fields:

- `frustration_baseline`
- `preferred_language`
- `typing_style`
- `availability_context`
- `managerial_responsibility`

### Scenario Schema

Each scenario must include:

- `scenario_id`
- `domain`
- `intent`
- `expected_retrieval_topics`
- `failure_injection`
- `success_criteria`

Because the chatbot app has no tool calls, the active schema should not require `tool_expectations`. If legacy contracts include `tool_expectations`, the validator should allow the field but mark it as ignored with a warning.

Failure injection controls:

- `ambiguity`
- `missing_information`
- `typos`
- `frustration`
- `policy_boundary_pressure`
- `contradictory_inputs`
- `repeated_clarification_loop`

Success criteria:

- `answers_grounded_in_policy`
- `asks_clarifying_question_if_needed`
- `does_not_disclose_other_employee_data`
- `proper_escalation_when_required`
- `safe_boundary_handling`

### Traffic Orchestration Schema

Required fields:

- `total_conversations`
- `conversation_turns.min`
- `conversation_turns.max`
- `mix`

Optional fields:

- `burst_patterns`
- `synthetic_day_distribution`
- `random_seed`
- `max_concurrency`
- `batch_size`
- `rate_limit_per_minute`

The `mix` array defines weighted persona-scenario pairs. Burst patterns adjust the daily distribution without changing the overall contract source of truth.

---

## 6. Chatbot Client

Build a thin chatbot wrapper with a deliberately small contract.

Request features:

- `conversation_id`
- `session_id`
- `turn_id`
- user message
- optional persona/scenario metadata
- optional synthetic/eval headers when supported by the endpoint

Response capture:

- raw response body
- extracted bot response text
- latency in milliseconds
- HTTP status
- error details

Do not implement tool-call extraction in the active client. Do not require retrieval telemetry. If the chatbot response happens to include retrieved policy IDs in the future, capture them opportunistically, but all active flows must work when that field is absent.

---

## 7. ChatHistory Simulation Engine

The simulation engine produces synthetic HR chatbot conversations.

Responsibilities:

- Load and validate the simulation contract.
- Create a deterministic run plan from `random_seed` when provided.
- Sample persona and scenario pairs from weighted traffic mix.
- Assign each conversation to a `synthetic_day`.
- Apply burst patterns such as open-enrollment spikes.
- Generate 3-8 turns per conversation according to the configured min/max.
- Generate user behavior instructions from persona, scenario, and failure-injection controls.
- Generate user messages with realistic variability.
- Call the chatbot endpoint unless running in dry-run mode.
- Score responses locally when enough information is available.
- Write ChatHistory and run-summary artifacts.

The engine should be async-capable:

- Execute conversations in batches.
- Respect `max_concurrency`.
- Respect `rate_limit_per_minute`.
- Continue partial runs when individual conversations fail.
- Record per-conversation errors without failing the entire batch unless configured to do so.

---

## 8. Failure and Variability Injection

The system must support controlled injection of:

- Typos
- Ambiguous wording
- Missing context
- Contradictory inputs
- Frustration escalation
- Repeated clarification loops
- Policy-boundary pressure
- Adversarial-lite prompts that are non-malicious but boundary-pushing

Each failure mode should be observable in local output through:

- `planned_failure_modes`
- `applied_failure_modes`
- `failure_mode`
- per-turn generation metadata

No explicit harmful content should be generated. Boundary-pressure and adversarial-lite prompts should remain HR-policy-safe and suitable for internal review.

---

## 9. Local Scoring

Because there is no production telemetry and no tool-call stream, scoring is local and best-effort.

Supported scores:

- `groundedness_score`: judge response against provided GoldenQA/policy context when available.
- `relevance_score`: judge response against the user message and scenario intent.
- `safety_score`: judge whether the response avoided data leakage and handled boundary pressure safely.
- `clarification_score`: judge whether the bot asked for clarification when scenario context was intentionally incomplete.

Do not include `tool_correctness` in active artifacts. Tool correctness belongs in backlog because the chatbot app does not expose tool calls.

Scores should be nullable when the required context or judge model is unavailable.

---

## 10. Artifact Outputs

This project writes local artifacts, not dashboard telemetry.

Required output directory:

```text
outputs/
  runs/
    <run_id>/
      contract.normalized.json
      run_plan.json
      chat_history.jsonl
      chat_history.csv
      conversations.jsonl
      turns.jsonl
      scores.jsonl
      run_summary.json
      generation_report.md
```

### ChatHistory Record Schema

Each turn-level ChatHistory record should include:

- `conversation_id`
- `session_id`
- `synthetic_day`
- `persona_id`
- `scenario_id`
- `turn_id`
- `user_message`
- `bot_response`
- `expected_retrieval_topics`
- `planned_failure_modes`
- `applied_failure_modes`
- `groundedness_score`
- `relevance_score`
- `safety_score`
- `clarification_score`
- `failure_mode`
- `latency_ms`
- `error`
- `synthetic_flag`

Optional fields:

- `retrieved_policy_ids`
- `response_raw`
- `generation_metadata`

Do not require:

- `tool_calls`
- `expected_tool_calls`
- `tool_correctness`
- dashboard-specific telemetry fields

---

## 11. Implementation Tasks

### Task 1: Package and CLI Foundation

**Files:**

- Create: `pyproject.toml`
- Create: `src/adaptive_synth_eval/__init__.py`
- Create: `src/adaptive_synth_eval/cli.py`
- Create: `tests/unit/test_cli.py`

- [ ] Create a minimal installable Python package.
- [ ] Add a CLI entrypoint named `adaptive-synth-eval`.
- [ ] Add `validate-contract`, `run`, and `summarize` command stubs.
- [ ] Add `--dry-run` support to `run`.
- [ ] Add CLI tests for command discovery and invalid contract path handling.
- [ ] Run `uv run pytest tests/unit/test_cli.py -q`.

### Task 2: Contract Schema and Example Contracts

**Files:**

- Create: `src/adaptive_synth_eval/config/schemas.py`
- Create: `src/adaptive_synth_eval/config/contract.py`
- Create: `contracts/examples/one_week_chat_history.yaml`
- Create: `contracts/examples/ten_k_conversations.yaml`
- Create: `tests/unit/test_contract.py`

- [ ] Define typed contract models for suite metadata, chatbot config, time window, persona pool, scenario catalog, traffic orchestration, scoring, and output.
- [ ] Support YAML and JSON loading.
- [ ] Validate persona required fields.
- [ ] Validate scenario required fields.
- [ ] Validate turn min/max and reject ranges outside 3-8 unless explicitly overridden.
- [ ] Warn but do not fail when legacy `tool_expectations` appears.
- [ ] Normalize defaults such as run ID, output path, random seed, batch size, and synthetic flag.
- [ ] Run `uv run pytest tests/unit/test_contract.py -q`.

### Task 3: Chatbot and LLM Clients

**Files:**

- Create: `src/adaptive_synth_eval/clients/chatbot.py`
- Create: `src/adaptive_synth_eval/clients/llm.py`
- Create: `tests/unit/test_chatbot_client.py`
- Create: `tests/unit/test_llm_client.py`

- [ ] Port useful HTTP behavior from `goldenQA/rag_client.py`.
- [ ] Normalize bot response text extraction across `response`, `answer`, `message`, `content`, `text`, and existing `llm_response`.
- [ ] Capture latency, HTTP status, raw response, and errors.
- [ ] Add dry-run/mock response support.
- [ ] Add tests with mocked HTTP responses.
- [ ] Run `uv run pytest tests/unit/test_chatbot_client.py tests/unit/test_llm_client.py -q`.

### Task 4: Traffic and Synthetic Day Planner

**Files:**

- Create: `src/adaptive_synth_eval/generation/traffic.py`
- Create: `tests/unit/test_traffic.py`

- [ ] Implement weighted persona-scenario sampling.
- [ ] Implement synthetic-day assignment across `num_synthetic_days`.
- [ ] Implement burst-pattern multipliers.
- [ ] Implement deterministic output with a configured `random_seed`.
- [ ] Validate that generated plan totals equal `total_conversations`.
- [ ] Run `uv run pytest tests/unit/test_traffic.py -q`.

### Task 5: Persona, Scenario, and Turn Generation

**Files:**

- Create: `src/adaptive_synth_eval/generation/personas.py`
- Create: `src/adaptive_synth_eval/generation/scenarios.py`
- Create: `src/adaptive_synth_eval/generation/variability.py`
- Create: `src/adaptive_synth_eval/generation/turns.py`
- Create: `tests/unit/test_generation.py`

- [ ] Convert persona and scenario records into generation instructions.
- [ ] Generate user turns with configured 3-8 turn depth.
- [ ] Apply typos, ambiguity, missing context, contradiction, frustration, repeated clarification, and policy-boundary pressure.
- [ ] Record planned and applied failure modes per turn.
- [ ] Keep adversarial-lite prompts non-malicious and HR-policy-safe.
- [ ] Run `uv run pytest tests/unit/test_generation.py -q`.

### Task 6: Local Scoring

**Files:**

- Create: `src/adaptive_synth_eval/scoring/response_quality.py`
- Create: `src/adaptive_synth_eval/scoring/failure_modes.py`
- Create: `tests/unit/test_scoring.py`

- [ ] Implement nullable score records for groundedness, relevance, safety, and clarification behavior.
- [ ] Use GoldenQA context where available.
- [ ] Detect local failure modes such as unsafe disclosure, missing clarification, off-topic answer, endpoint error, and empty response.
- [ ] Ensure no tool correctness score is produced in active artifacts.
- [ ] Run `uv run pytest tests/unit/test_scoring.py -q`.

### Task 7: Artifact Exporters

**Files:**

- Create: `src/adaptive_synth_eval/artifacts/schemas.py`
- Create: `src/adaptive_synth_eval/artifacts/exporters.py`
- Create: `tests/unit/test_exporters.py`

- [ ] Define ChatHistory, conversation, turn, score, and run-summary artifact records.
- [ ] Write `chat_history.jsonl`.
- [ ] Write `chat_history.csv`.
- [ ] Write `conversations.jsonl`, `turns.jsonl`, `scores.jsonl`, and `run_summary.json`.
- [ ] Ensure every ChatHistory row carries `synthetic_flag=true`.
- [ ] Ensure active artifacts do not require tool-call fields.
- [ ] Run `uv run pytest tests/unit/test_exporters.py -q`.

### Task 8: Simulation Engine

**Files:**

- Create: `src/adaptive_synth_eval/engines/chat_history_simulation.py`
- Create: `tests/unit/test_chat_history_simulation.py`

- [ ] Wire contract loading, traffic planning, turn generation, chatbot calls, local scoring, and artifact export.
- [ ] Support dry-run mode.
- [ ] Support async batch execution with `max_concurrency`.
- [ ] Preserve partial results when individual conversations fail.
- [ ] Write `generation_report.md` summarizing counts, personas, scenarios, days, failure modes, errors, and score availability.
- [ ] Run `uv run pytest tests/unit/test_chat_history_simulation.py -q`.

### Task 9: End-to-End CLI Runs

**Files:**

- Modify: `src/adaptive_synth_eval/cli.py`
- Create: `tests/integration/test_cli_runs.py`

- [ ] Wire `run --contract` to the ChatHistory simulation engine.
- [ ] Wire `summarize --run-id` to existing run artifacts.
- [ ] Add integration tests using dry-run mode and mocked chatbot responses.
- [ ] Verify output files are created with expected schemas.
- [ ] Run `uv run pytest tests/integration/test_cli_runs.py -q`.

### Task 10: Documentation and Team Handoff

**Files:**

- Create: `README.md` if not already present.
- Create: `docs/cli_usage.md`
- Create: `docs/contracts.md`
- Create: `docs/chat_history_schema.md`
- Create: `docs/failure_injection.md`
- Create: `docs/team_handoff.md`

- [ ] Document local setup.
- [ ] Document contract fields.
- [ ] Document one-week ChatHistory generation.
- [ ] Document 10,000-conversation generation.
- [ ] Document dry-run mode.
- [ ] Document failure injection.
- [ ] Document what is explicitly out of active scope.
- [ ] Add a short team-handoff guide for laptop usage.
- [ ] Run the full test suite with `uv run pytest -q`.

---

## 12. Milestones

### Milestone 1: Runnable Skeleton

Done when:

- CLI installs and runs.
- Contracts validate.
- Dry-run mode creates artifact directories.
- Example contracts are included.

### Milestone 2: Synthetic Generation

Done when:

- Persona-scenario sampling works.
- Synthetic-day assignment works.
- Burst patterns work.
- 3-8 turn user conversations can be generated.
- Failure injection is visible in output.

### Milestone 3: Chatbot-Connected Runs

Done when:

- The CLI can call the chatbot endpoint.
- Raw responses and bot text are captured.
- Endpoint errors are recorded without losing the entire run.
- Local scoring runs when configured.

### Milestone 4: Scale and Handoff

Done when:

- One-week ChatHistory can be generated for 30 users per hour across at least two profiles.
- A 10,000-conversation run can complete in dry-run or chatbot-connected mode, depending on endpoint availability.
- Documentation is complete.
- The Evals team can run the package from a laptop.

---

## 13. Risks and Controls

| Risk | Control |
|---|---|
| Chatbot API schema remains unclear | Keep the chatbot client small and response extraction flexible. Support dry-run and mocked responses. |
| No production telemetry is available | Treat all observability-style fields as generated/local artifacts only. Do not require dashboard ingestion. |
| No tool-call stream exists | Keep tool-call validation out of active scope and warn when legacy contracts include tool expectations. |
| 10,000 conversation generation is expensive | Support dry-run mode, batching, concurrency limits, rate limits, and resumable partial outputs. |
| Synthetic data quality is too uniform | Use weighted persona-scenario mix, synthetic-day distribution, burst patterns, and failure-injection probabilities. |
| Boundary-pressure prompts become too aggressive | Keep adversarial-lite generation non-malicious, HR-policy-safe, and suitable for internal review. |

---

## 14. Backlog

These items are explicitly out of the active implementation path but should remain documented for future work.

### Azure AI Evaluation Simulator

- Add Azure Simulator as an optional execution engine.
- Convert internal persona/scenario instructions into simulator-compatible task prompts.
- Use callbacks to call the HR chatbot endpoint.

### Dashboard Telemetry and Observability Ingestion

- Emit dashboard-specific telemetry records.
- Match the observability platform schema exactly.
- Add ingestion validation.
- Produce an observability deck or continuous monitoring hourly showcase.

### Tool-Calling Validation

- Add `tool_calls`, `expected_tool_calls`, and `tool_correctness` only if the chatbot app starts exposing tool calls.
- Validate missed required tool calls.
- Validate unnecessary tool invocation.
- Validate incorrect Jira creation.
- Validate unauthorized data access through tool output.

### Advanced Adversarial Harness

- Restore the adaptive adversarial harness as a separate phase.
- Use `better-harness` to optimize planner, generator, judge, policy, and scoring surfaces.
- Keep this separate from the HR ChatHistory CLI until the base package is stable.

### Vendor Evaluation and Stress Testing

- Add vendor/model comparison runs.
- Add load/stress profiles.
- Add cost and latency benchmarking.

---

## 15. Final Deliverables

The active project is complete when it can produce:

- A generated ChatHistory dataset containing one week of synthetic chat at 30 users per hour across at least two profiles.
- At least 10,000 generated synthetic multi-turn conversations with 3-8 turns.
- Contract-driven personas, scenarios, weighted traffic mix, synthetic days, burst patterns, and failure injection.
- Local artifacts: `chat_history.jsonl`, `chat_history.csv`, `run_plan.json`, `run_summary.json`, and `generation_report.md`.
- A packaged CLI that the Evals team can run locally.
- GitHub/Confluence-ready documentation and a team handoff guide.
