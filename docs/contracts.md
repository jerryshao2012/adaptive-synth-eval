# Simulation Contracts

Contracts are JSON or YAML and are the source of truth for simulation behavior.

Required sections:

- `simulation_suite`
- `target`
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

This is particularly useful for the `target.endpoint` field to avoid hardcoding endpoints:

```yaml
target:
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
target:
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

## AWS AgentCore Target Mode

When your chatbot is deployed to AWS Bedrock AgentCore runtime, configure the target in `agentcore` mode.

```yaml
target:
  enabled: true
  mode: agentcore
  timeout_seconds: 60
  agentcore:
    region: "${AWS_REGION:-us-east-1}"
    agent_runtime_arn: "${TFSA_AGENTCORE_RUNTIME_ARN}"
    qualifier: "${TFSA_AGENTCORE_QUALIFIER:-DEFAULT}"
    payload_prompt_key: prompt
    runtime_session_id_prefix: ase_
```

AgentCore mode uses the following fields:

- `region`: AWS region where the runtime exists.
- `agent_runtime_arn`: full AgentCore runtime ARN.
- `qualifier`: optional endpoint qualifier (for example `DEFAULT`).
- `payload_prompt_key`: payload key used to pass user text (defaults to `prompt`).
- `runtime_session_id_prefix`: prefix used to derive stable 33+ character runtime session IDs from ASE conversation/session IDs.

Authentication for AgentCore mode comes from the active AWS credentials/profile used by `boto3`.
```bash
aws configure
aws sts get-caller-identity
```

## Unified Contracts

Unified contracts support interleaving synthetic (ASE) and adversarial (ARE) red-teaming turns. A unified contract uses the `suite` block instead of `simulation_suite`, and requires the `eval_plan` block. To define adversarial scenarios, you can either configure them under the main `scenario_catalog` block alongside synthetic parameters, or use a separate optional `adversarial_scenario_catalog` block. For details on unified contract structures, see [Unified Evaluation Guide](unified_evaluation.md).

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

### 2. `unified_evaluation_demo.yaml` (Unified)
- **Purpose**: A comprehensive unified evaluation contract illustrating multi-persona usage and all four adversarial scenario types (toxicity, prompt-injection, PII leak, and persona-hijack).
- **Run Limit**: 15 conversations, 3-5 turns each.
- **Key Features**:
  - 3 personas: New employee, Manager, and Contractor using domain-neutral schema fields.
  - 4 scenarios: Benefits enrollment (with inline PII leak checks), Leave policy (with inline persona-hijack checks), Toxicity testing, and Prompt injection.
  - Interleaving modes: `phased`, `min_each`, and `bernoulli` schedules.
- **Validation**:
  ```bash
  uv run ase validate-contract contracts/examples/unified_evaluation_demo.yaml
  ```
- **Execution**:
  ```bash
  uv run ase run --contract contracts/examples/unified_evaluation_demo.yaml --dry-run
  ```

### 3. `tfsa_aws_unified_evaluation.yaml` (Unified)
- **Purpose**: A unified evaluation contract targeting a Tax-Free Savings Account (TFSA) chatbot deployed on AWS.
- **Run Limit**: 12 conversations, 3-6 turns each.
- **Key Features**:
  - AWS Bedrock AgentCore runtime target (`mode: agentcore`) with configurable runtime ARN and qualifier.
  - TFSA customer personas: Novice saver, Experienced investor, Self-employed contractor.
  - Scenarios: Eligibility & limits, Withdrawals, PII Leak (protecting SIN), Persona Hijack (certified advisor boundaries), Toxicity, and Prompt injection.
- **Validation**:
  ```bash
  uv run ase validate-contract contracts/examples/tfsa_aws_unified_evaluation.yaml
  ```
- **Execution**:
  ```bash
  uv run ase run --contract contracts/examples/tfsa_aws_unified_evaluation.yaml --dry-run
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

#### 8. `unified_evaluation_demo.yaml`
- **Purpose**: Demonstrates unified adversarial and synthetic capabilities with 3 distinct user types interacting with 2 different scenarios
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

#### 9. `tfsa_aws_unified_evaluation.yaml`
- **Purpose**: Demonstrates unified synthetic and adversarial capabilities on a Tax-Free Savings Account (TFSA) chatbot.
- **Key Features**:
  - Simulates 12 conversations with lengths between 3 and 6 turns.
  - Endpoint configuration includes API key authentication via `type: api_key`, protecting an AWS-deployed service.
  - 3 custom personas targeting different demographics: novice savers, experienced investors, and contractors.
  - Scenarios cover Canadian TFSA rules (eligibility, limits, withdrawal timing) alongside security/safety guardrails (PII leakage, professional persona hijacking, toxicity, and prompt injections).
- **Use Case**: Testing safety boundary compliance, content filtering, and specific regulatory rules on tax-advantaged account domains.

