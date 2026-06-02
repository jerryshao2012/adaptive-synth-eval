# Simulation Contracts

Contracts are JSON or YAML and are the source of truth for simulation behavior.

Required sections:

- `simulation_suite`
- `target_chatbot`
- `time_window`
- `persona_pool`
- `scenario_catalog`
- `traffic_orchestration`
- `output`

Tool-call expectations are not active scope. If a legacy contract includes `tool_expectations`, validation warns and ignores the field.

Conversation turn ranges must be within 3-8 turns.

## Environment Variable Substitution

Contract files support environment variable substitution using `${VAR_NAME}` syntax:

- `${CHATBOT_ENDPOINT}` - replaced with the value of the `CHATBOT_ENDPOINT` environment variable
- `${CHATBOT_ENDPOINT:-https://default.example.com}` - uses the env var if set, otherwise falls back to the default value

This is particularly useful for the `target_chatbot.endpoint` field to avoid hardcoding endpoints:

```yaml
target_chatbot:
  enabled: true
  endpoint: "${CHATBOT_ENDPOINT:-https://api.example.com/v1/chat}"
  retry_max_retries: 2
  retry_initial_backoff_seconds: 1.0
  retry_max_backoff_seconds: 20.0
  retry_backoff_multiplier: 2.0
  retry_jitter: true
  retry_on_timeout: true
  retry_on_http_5xx: false
  auth:
    type: bearer
    env_var: CHATBOT_API_TOKEN
```

When `CHATBOT_ENDPOINT` is set in your environment, it will override the default. Otherwise, the fallback value is used.

Retry fields are optional and control how API chatbot requests handle transient failures before the simulation marks the chatbot as unavailable:

- `retry_max_retries`: number of retry attempts after the first failed attempt.
- `retry_initial_backoff_seconds`: base delay before the first retry.
- `retry_max_backoff_seconds`: upper bound for exponential backoff.
- `retry_backoff_multiplier`: multiplier for each retry delay.
- `retry_jitter`: randomize delays to reduce synchronized bursts.
- `retry_on_timeout`: retry transport-level timeout/connection errors.
- `retry_on_http_5xx`: retry HTTP `429/500/502/503/504` responses.

## Browser Chatbot Mode

The chatbot can also be driven through a generic browser UI instead of an HTTP API. This is useful when the target chatbot only exposes a web chat surface.

```yaml
target_chatbot:
  enabled: true
  mode: browser
  browser:
    browser_type: edge
    url: "https://chat.example.com"
    input_selector: "textarea"
    submit_selector: "button[type='submit']"
    response_selector: ".bot-message"
    ready_selector: "textarea"
    response_timeout_seconds: 60
    headless: false
```

Browser mode uses the following fields:

- `browser_type`: browser engine to launch. Options: `chromium` (default) or `edge` (which launches Microsoft Edge using Playwright's `msedge` channel).
- `input_selector`: element that receives the user message.
- `submit_selector`: element clicked to send the message.
- `response_selector`: bot message elements; the newest matching element is captured.
- `ready_selector`: optional element to wait for after page load. Defaults to `input_selector`.

Browser mode runs chatbot calls sequentially, even if `traffic_orchestration.max_concurrency` is higher, because a single browser chat page cannot safely process concurrent turns.

## Unified Contracts

Unified contracts support interleaving synthetic (ASE) and adversarial (ARE) red-teaming turns. A unified contract uses the `suite` block instead of `simulation_suite`, and requires `eval_plan` and `adversarial_scenario_catalog` blocks. For details on unified contract structures, see [Unified Evaluation Guide](unified_evaluation.md).

## Available Examples

### 1. `chatbot_test_contract.yaml` (Synthetic Only)
- **Purpose**: Validation and dry-run testing for synthetic-only conversations.
- **Run Limit**: 5 conversations, 3-5 turns each.
- **Validation**:
  ```bash
  uv run ase validate-contract contracts/examples/chatbot_test_contract.yaml
  ```
- **Execution**:
  ```bash
  uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
  ```

### 2. `mock_unified_quickstart.yaml` (Unified)
- **Purpose**: Fast, dependency-free dry run demonstrating interleaved synthetic and adversarial turns.
- **Run Limit**: 2 conversations, 3 turns each.
- **Schedule**: `min_each` with 1 synthetic turn and 1 adversarial turn guaranteed.
- **Validation**:
  ```bash
  uv run ase validate-contract contracts/examples/mock_unified_quickstart.yaml
  ```
- **Execution**:
  ```bash
  uv run ase run --contract contracts/examples/mock_unified_quickstart.yaml --dry-run --output-conversations
  ```

### 3. `hr_policy_unified.yaml` (Unified)
- **Purpose**: A comprehensive HR-themed unified contract testing standard HR scenarios alongside policy boundaries and PII leaks.
- **Run Limit**: 4 conversations, 3-6 turns each.
- **Schedule**: `phased` schedule with 2 warmup synthetic turns, followed by adversarial probes.
- **Validation**:
  ```bash
  uv run ase validate-contract contracts/examples/hr_policy_unified.yaml
  ```

### 4. `adversarial_heavy.yaml` (Unified)
- **Purpose**: A red-teaming heavy evaluation designed to focus primarily on red-teaming target chatbots.
- **Run Limit**: 4 conversations, 4-6 turns each.
- **Schedule**: `bernoulli` with `p_synth: 0.1` (90% adversarial probe chance).
- **Validation**:
  ```bash
  uv run ase validate-contract contracts/examples/adversarial_heavy.yaml
  ```

### Additional Examples

#### 5. `one_week_chat_history.yaml`
- **Purpose**: A comprehensive 7-day simulation plan simulating realistic HR chatbot usage over a week
- **Key Features**:
  - Simulates 5,040 conversations across 7 days (compressed into 60 minutes runtime)
  - 2 personas: New employee (P001) and Manager (P002) with different communication styles
  - 2 scenarios: Parental leave policy and benefits enrollment
  - Includes burst pattern: 3x traffic spike on day 3 for open enrollment
  - Traffic mix: 45% new employee + parental leave, 20% new employee + benefits, 15% manager + parental leave, 20% manager + benefits
  - Failure injection includes ambiguity (0.4), missing info (0.3), typos, frustration, and policy boundary pressure
- **Use Case**: Testing long-term conversation patterns, burst handling, and multi-persona interactions over time

#### 6. `browser_chatbot_test.yaml`
- **Purpose**: A focused contract for testing browser-driven chatbot integration (not API-based)
- **Key Features**:
  - Uses `mode: browser` instead of HTTP endpoint
  - Browser configuration: Chromium engine, non-headless mode
  - CSS selectors defined for input (`#chat-input textarea`), submit button (`#send-button`), and response capture (`.bot-message .message-content`)
  - Single tester persona (BROWSER_TEST_P1) with direct communication style
  - Tests browser automation functionality including UI rendering
  - Small scale: 5 conversations, 3-5 turns each, 3 synthetic days compressed to 15 minutes
  - Max concurrency limited to 2 (browser mode runs sequentially per page)
- **Use Case**: Validating chatbots that only expose web UI interfaces, testing Playwright browser automation integration

#### 7. `ten_k_conversations.yaml`
- **Purpose**: A large-scale stress test contract generating 10,000 conversations for performance validation
- **Key Features**:
  - Massive scale: 10,000 conversations across 30 synthetic days (compressed to 60 minutes)
  - Same 2 personas as one_week but scaled up significantly
  - Higher concurrency: max_concurrency=10, batch_size=250
  - Burst pattern: 4x traffic spike on day 12 for open enrollment (benefits, leave, payroll scenarios)
  - Traffic distribution: 35% P001+S001, 25% P001+S002, 15% P002+S001, 25% P002+S002
  - Random seed 314 for reproducibility at scale
  - Target chatbot disabled (synthetic-only generation)
- **Use Case**: Performance benchmarking, scalability testing, load testing the generation pipeline, validating system behavior under high-volume conditions

#### 8. `multi_persona_demo.yaml`
- **Purpose**: Demonstrates multi-persona capabilities with 3 distinct user types interacting with 2 different scenarios
- **Key Features**:
  - 3 diverse personas:
    - DEMO_P1: New employee from Toronto (junior, confused_but_polite, low HR familiarity)
    - DEMO_P2: Manager from Vancouver (senior, direct_under_time_pressure, high HR familiarity, high privacy sensitivity)
    - DEMO_P3: Remote contractor (mid-level, casual_and_brief, medium HR familiarity, low privacy sensitivity)
  - 2 scenarios: Benefits enrollment and leave policy requests
  - 15 total conversations showing weighted distribution across all persona-scenario combinations
  - Most common: New employee asking about benefits (35% weight)
  - Least common: Contractor asking about leave (5% weight)
  - Real-time chat enabled with target chatbot
  - Max concurrency: 3, batch size: 15
- **Use Case**: Showcasing how different user types (roles, seniority, locations, communication styles) interact with the same chatbot, demonstrating persona diversity and realistic traffic mixing
