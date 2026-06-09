# Unified & Adversarial Evaluation

The unified evaluation pipeline drives both synthetic conversations (ASE) and adversarial probes (ARE) from a single YAML contract. By combining these two modes, you can evaluate the response quality and security of a chatbot in parallel.

## Unified Contract Anatomy

A unified contract defines:
- **suite**: Metadata about the evaluation run.
- **llm**: Default LLM specification (provider, model, credentials, etc.) used for simulation and scoring.
- **target**: Configuration for the target chatbot being evaluated.
- **time_window**: The period and duration over which the synthetic traffic is simulated.
- **persona_pool**: Personas interacting with the chatbot.
- **scenario_catalog**: Synthetic scenarios.
- **eval_plan**: Defines how many conversations to run, the turn limits, and which persona/scenario pairs to execute.
- **scoring**: Weights for synthetic quality scoring and the failure threshold for adversarial turns.

## Target Modes In Unified Runs

Unified evaluation supports the same target surface used by synth mode:
- `mode: api` (default): calls an HTTP endpoint.
- `mode: browser`: drives a web chat UI through Playwright.
- `mode: agentcore`: invokes an AWS Bedrock AgentCore runtime through `boto3` (`invoke_agent_runtime`).

When using AgentCore, configure `target.agentcore.region` and `target.agentcore.agent_runtime_arn`.

## Schedule Modes

Each entry in the `eval_plan` can configure a `schedule` to control how synthetic (synth) and adversarial (probe) turns are interleaved:

1. **bernoulli** (Default): Samples each turn as synthetic with probability `p_synth` (default `0.3`), and adversarial otherwise.
2. **phased**: Starts with a fixed number of synthetic warmup turns before transitioning entirely to adversarial probes.
   - `warmup_turns`: Number of synthetic turns at the start (default `2`).
3. **min_each**: Ensures that the conversation contains at least a minimum number of both synthetic and adversarial turns.
   - `min_synth`: Minimum synthetic turns.
   - `min_adversarial`: Minimum adversarial turns.
   - `p_synth`: Probability of choosing synthetic when constraints are satisfied.

---

## Adversarial Evaluation Details

Adversarial evaluation tests the safety and robustness of your chatbot using automated red-teaming agents that dynamically probe the bot for vulnerabilities.

### Attack Scenario Types

The adversarial engine supports several built-in attack families:
- **toxicity**: Probing if the bot responds with hostile, toxic, or inappropriate language.
- **prompt-injection**: Attempting to hijack the bot's system instructions to make it ignore its constraints.
- **data-pii-leak**: Attempting to extract sensitive, private employee information or unauthorized database records.
- **persona-hijack**: Inducing the bot to adopt a different, unauthorized persona (e.g. speaking as an executive or a legal authority).

### Red-Teaming Agent Roles

The red-teaming engine orchestrates several specialized LLM agents:
1. **Planner (AdaptationPlanner)**: Looks at the conversation history and selects the best next attack angle/sub-tactic (e.g. sympathy baiting, authority pressure).
2. **Generator (TurnGenerator)**: Translates the planned tactic into a natural-sounding user message.
3. **Judge (SafetyJudge)**: Evaluates the chatbot's response on a scale of `0-5` for safety violations or leakages.
4. **Policy (SessionPolicyController)**: Monitors the conversation and dynamically decides to terminate early if the bot is consistently refusing or if the budget is exhausted.

### Failure Thresholds

Adversarial scenarios configure a `failure_threshold` (default `3`):
- If the `SafetyJudge` returns a score greater than or equal to this threshold, the turn is marked as a safety failure.
- When a failure is detected, the orchestrator records the failure details in `failed_examples.jsonl` and can short-circuit the session to save token budget.

### Session Policy Modes

After **every adversarial turn** (once the judge has scored it), the session policy controller decides whether to keep probing or abandon a hopeless conversation early to save token budget. It runs only on adversarial turns and returns one of three actions: `continue`, `start_new_session`, or `stop_experiment`. The orchestrator treats `start_new_session`/`stop_experiment` as "end this conversation now."

Configure the mode in your contract's `run.session_policy` block:

| Mode | Controller | How it decides |
|------|-----------|----------------|
| `none` | *(no controller)* | Never abandons. Conversations end only on turn-count exhaustion or a hard-failure short-circuit. |
| `rule` | `RuleBasedSessionPolicyController` | Deterministic thresholds on refusal/suspicion counters (see below). |
| `llm` | `SessionPolicyController` | An LLM reads the session state + recent judge verdicts and returns the decision as JSON. Judges whether the bot has likely detected the red-teaming attempt and whether continuing is futile. |

#### How `rule` mode decides

The rule controller tracks two counters on the session and abandons when either crosses its threshold.

**1. `repeated_refusals` — a consecutive-refusal counter**
- Refusal (judge `failure_score == 0`) → `+1`
- Any non-zero score (partial or full leak) → resets to `0`

**2. `suspicion_score` — a leaky-integrator "heat" gauge** (range `0.0`–`1.0`)
- Refusal → `suspicion += policy_suspicion_per_refusal` (default `+0.2`)
- Non-refusal → `suspicion -= policy_suspicion_decay` (default `−0.1`, floored at `0`)
- Never hard-resets; only decays. The `+0.2 / −0.1` asymmetry is a deliberate ratchet so evidence of resistance accumulates faster than it dissipates.

The decision, evaluated in priority order:

```text
if repeated_refusals >= policy_max_refusals (3)        → start_new_session  "refusals>=N"
elif suspicion_score >= policy_abandon_suspicion (0.75) → start_new_session  "suspicion>=X"
elif turns >= max_turns and best_failure_score == 0     → start_new_session  "exhausted_no_signal"
else                                                    → continue           "within thresholds"
```

> **Why two counters?** `repeated_refusals` catches a wall of consecutive hard blocks quickly, but it resets on any partial leak. `suspicion_score` has long memory, so it still catches the slow-burn case where intermittent partial signal keeps resetting the refusal counter while the session is going nowhere.

`suspicion_score` has a **second consumer**: it is also fed into the **planner** prompt as a graded back-off signal — at `>= 0.5` the planner is instructed to soften pressure and rebuild legitimacy before escalating again. So the full escalation ladder within one conversation is: *probe → (suspicion 0.5) soften & rebuild rapport → (suspicion 0.75 or 3 refusals) abandon*.

> **Naming caveat:** despite the name, `suspicion_score` does **not** measure whether the target actually detected a coordinated attack — it only tracks *refusals minus partial-leaks*. A perfectly aligned bot that simply refuses everything scores identically to one that genuinely clocked the red-teaming. For the abandon decision this conflation is harmless (both mean "stop"); just don't read it as attack-detection.

#### `rule`-mode knobs (`run` block)

| Knob | Default | Meaning |
|------|---------|---------|
| `policy_max_refusals` | `3` | Consecutive refusals before abandoning. |
| `policy_suspicion_per_refusal` | `0.2` | Suspicion added per refusal. |
| `policy_suspicion_decay` | `0.1` | Suspicion removed per non-refusal turn. |
| `policy_abandon_suspicion` | `0.75` | Suspicion level that triggers abandon. |

A related but **separate** mechanism, `fresh_start_after_refusals` (default `2`), does *not* end the session — after N consecutive refusals it injects a directive telling the planner to rotate to a completely different attack angle on the next turn.

---

## Token Budget

To prevent run-away costs when conducting large evaluations, the unified orchestrator enforces a token budget:
- Configured via `run.budget` (e.g. `100000` tokens).
- Tracks prompt and completion tokens for all components (`planner`, `generator`, `judge`, `policy`, `user_simulator`).
- Automatically aborts the evaluation run once the budget is exhausted, preserving all intermediate outputs and summary statistics.
