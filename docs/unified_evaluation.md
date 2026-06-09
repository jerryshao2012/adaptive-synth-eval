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

For `mode: api`, you can also set optional target LLM payload knobs in the `target` block:
- `chatbot_model`: list of model identifiers forwarded in request payload.
- `chatbot_temperature`: temperature forwarded in request payload.
- `source_doc_ref`: source document reference forwarded in request payload.

These can be configured directly in the contract, and if omitted, they can fall back to env vars:
- `CHATBOT_MODEL`
- `CHATBOT_TEMPERATURE`
- `CHATBOT_SOURCE_DOCUMENT_REFERENCE`

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

To optimize costs, you can configure a session policy in your contract's `run.session_policy` block:
- **none**: Runs conversations to their full turn limit.
- **rule**: Evaluates simple rules (e.g. abort if there are too many consecutive chatbot refusals).
- **llm**: Employs an LLM to judge if the chatbot has detected the red-teaming attempt and if continuing is futile.

---

## Token Budget

To prevent run-away costs when conducting large evaluations, the unified orchestrator enforces a token budget:
- Configured via `run.budget` (e.g. `100000` tokens).
- Tracks prompt and completion tokens for all components (`planner`, `generator`, `judge`, `policy`, `user_simulator`).
- Automatically aborts the evaluation run once the budget is exhausted, preserving all intermediate outputs and summary statistics.
