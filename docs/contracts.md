# Contract Reference

ASE contracts are YAML or JSON files that define the target, simulated users, scenarios, traffic, scoring, and outputs. The loader selects the evaluation mode from the top-level key: `simulation_suite` selects synth mode, while `suite` selects unified mode.

Use [`ase validate-contract`](cli_usage.md) before a run. For runtime behavior, see the [unified evaluation guide](unified_evaluation.md); for generated files and field definitions, see the [artifact reference](output_artifacts.md).

## Environment substitution

Any contract value may use `${NAME}` or `${NAME:-default}`. Secrets should be referenced by environment-variable name rather than embedded as literal values. See [environment setup](environment_setup.md) for credentials, TLS, proxy, and provider prerequisites.

## Synth contracts

Synth contracts generate persona-driven conversations without adversarial turns.

### Required blocks

| Block | Purpose |
| :--- | :--- |
| `simulation_suite` | Suite ID, target application, run mode, and synthetic flag |
| `target` | Target client and retry settings |
| `time_window` | Start date, synthetic days, and compressed runtime |
| `persona_pool` | Personas available to the traffic mix |
| `scenario_catalog` | Benign tasks and optional failure injection |
| `traffic_orchestration` | Conversation count, turn range, weighted mix, bursts, and concurrency |

`output` is optional and defaults to `outputs`; `llm` is optional and configures the user simulator. If no simulator provider is configured or detected, synth mode uses deterministic templates.

```yaml
simulation_suite:
  suite_id: example_synth
  target_application: example_bot
  run_mode: synth
  synthetic_flag: true

target:
  enabled: true
  mode: api
  endpoint: "${CHATBOT_ENDPOINT}"

llm:
  provider: openai
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY

time_window:
  start_day: 2026-01-01
  num_synthetic_days: 1
  compressed_runtime_minutes: 5

persona_pool: []
scenario_catalog: []

traffic_orchestration:
  total_conversations: 10
  conversation_turns: {min: 3, max: 5}
  mix: []
  max_concurrency: 5

output:
  base_dir: outputs
```

Synth validation requires conversation turns in the inclusive range 3–8, `min <= max`, and every `traffic_orchestration.mix` persona/scenario reference to exist. A legacy scenario `tool_expectations` field is accepted with a warning and ignored.

## Unified contracts

Unified contracts interleave synth and adversarial turns within one conversation.

### Required blocks

| Block | Purpose |
| :--- | :--- |
| `suite` | Suite metadata; `run_mode` defaults to `unified` |
| `llm` | Default harness LLM specification |
| `target` | Target client configuration |
| `time_window` | Synthetic dates and compressed runtime |
| `persona_pool` | Personas available to plan entries |
| `scenario_catalog` | Synth scenarios; may also contain inline adversarial scenarios |
| `eval_plan` | Turn range, weighted conversation recipes, schedules, and attack-memory mode |

Optional blocks are `schema_version`, `run`, `components`, `adversarial_scenario_catalog`, `scoring`, `trajectory`, and `output`. Unified source contracts may omit `schema_version`; the normalized artifact is always canonical schema version 2. Versions 1 and 2 are accepted, and future versions are rejected.

```yaml
schema_version: 2
suite:
  suite_id: example_unified
  target_application: example_bot
  run_mode: unified

run:
  random_seed: 42
  max_concurrency: 5
  budget: 200000
  session_policy: rule

llm:
  provider: bedrock
  model: anthropic.claude-3-5-sonnet-20241022-v2:0
  max_tokens: 1024
  bedrock:
    region: us-east-1

components:
  judge:
    provider: bedrock
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
    bedrock: {region: us-east-1}

target:
  enabled: true
  mode: api
  endpoint: "${CHATBOT_ENDPOINT}"

time_window:
  start_day: 2026-01-01
  num_synthetic_days: 1
  compressed_runtime_minutes: 5

persona_pool: []
scenario_catalog: []
adversarial_scenario_catalog: []

eval_plan:
  total_conversations: 10
  conversation_turns: {min: 3, max: 8}
  attack_memory: shared
  entries: []

scoring:
  adversarial: {failure_threshold: 3}

trajectory:
  enabled: false
  trace_field: trace

output:
  base_dir: outputs
```

Unified validation requires conversation turns in the inclusive range 1–20, `min <= max`, valid plan references, a target LLM block when `target.mode: llm`, and a supported schedule and memory mode.

### LLM specifications

The top-level `llm` is the default for planner, generator, judge, policy, and user simulator. `components.planner`, `components.generator`, `components.judge`, `components.policy`, and `components.user_simulator` may override it. An LLM target uses `target.chatbot_llm` plus optional `target.system_prompt`.

Unified contracts require an explicit `llm` specification. The unified factory accepts
`mock`, `claude`, `openai`, `azure-openai`, `bedrock`, and `ollama`. These names are not
interchangeable with every synth/legacy simulator alias: for example, unified uses
`claude` and `azure-openai`, while the synth client uses `anthropic` and normalized
`azure_openai`.

> **Unified Ollama limitation:** the unified factory uses real Ollama only for the user
> simulator interface. ARE planner, generator, and judge interfaces fall back to the mock
> backend. A unified run configured with `provider: ollama` is therefore not a real
> Ollama-backed adversarial evaluation, and its adversarial scores must not be interpreted
> as such.

Canonical schema-v2 provider settings are nested. For Azure OpenAI:

```yaml
llm:
  provider: azure-openai
  model: gpt-4o-mini
  max_tokens: 1024
  temperature: 0.7
  api_key_env: AZURE_OPENAI_API_KEY
  azure:
    endpoint: "${AZURE_OPENAI_ENDPOINT}"
    deployment: "${AZURE_OPENAI_DEPLOYMENT}"
    api_version: "${AZURE_OPENAI_API_VERSION:-2024-12-01-preview}"
```

For native AWS Bedrock:

```yaml
llm:
  provider: bedrock
  model: anthropic.claude-3-5-sonnet-20241022-v2:0
  max_tokens: 1024
  bedrock:
    region: us-east-1
```

The unified Bedrock backend uses the standard `boto3` AWS credential chain. Its region
resolution is `bedrock.region`, then `AWS_DEFAULT_REGION`, then `us-east-1`. This differs
from the synth/legacy client's bearer-token, OpenAI-compatible Bedrock path. See
[environment setup](environment_setup.md) for credential prerequisites.

Legacy flat names (`azure_endpoint`, `azure_deployment`, `azure_api_version`, `bedrock_region`, `bedrock_endpoint`, and `ollama_base_url`) remain accepted at top-level, component, and target LLM locations. When a nested and flat value conflict, the nested value wins and validation emits a warning. Although `bedrock.endpoint`/`bedrock_endpoint` round-trip for compatibility, the current unified native Bedrock backend does not use a custom endpoint.

## Target modes

All modes reuse the same target schema.

### API target

`mode: api` is the default. Configure `endpoint`, `auth`, `timeout_seconds`, and optional retry fields. `chatbot_model`, `chatbot_temperature`, and `source_doc_ref` are forwarded in the request payload; contract values take precedence over `CHATBOT_MODEL`, `CHATBOT_TEMPERATURE`, and `CHATBOT_SOURCE_DOCUMENT_REFERENCE`.

### Browser target

```yaml
target:
  enabled: true
  mode: browser
  browser:
    browser_type: chromium # or edge
    url: https://chat.example.com
    input_selector: textarea
    submit_selector: "button[type='submit']"
    response_selector: .bot-message
    ready_selector: textarea
    response_timeout_seconds: 60
    headless: false
```

A single browser chat page processes target calls sequentially.

### AgentCore target

```yaml
target:
  enabled: true
  mode: agentcore
  timeout_seconds: 60
  agentcore:
    region: "${AWS_REGION:-us-east-1}"
    agent_runtime_arn: "${AGENT_RUNTIME_ARN}"
    qualifier: "${AGENTCORE_QUALIFIER:-DEFAULT}"
    payload_prompt_key: prompt
    runtime_session_id_prefix: ase_
```

Authentication comes from the active AWS credentials used by `boto3`.

### LLM target

Unified mode also supports `mode: llm` with `target.chatbot_llm`. In non-dry-run mode,
the current `LLMTargetClient` supports only `provider: claude`; other providers fail when
the client is built. This evaluates a directly configured Claude model instead of an API,
browser, or AgentCore application.

```yaml
target:
  enabled: true
  mode: llm
  system_prompt: You are a helpful assistant.
  chatbot_llm:
    provider: claude
    model: claude-haiku-4-5-20251001
    api_key_env: ANTHROPIC_API_KEY
```

## Unified schedules

Each `eval_plan.entries[]` selects a persona, synth scenario, adversarial scenario, weight, optional `max_turns`, and schedule:

| Mode | Fields | Behavior |
| :--- | :--- | :--- |
| `bernoulli` | `p_synth` | Independent synth/adversarial choice each turn; default `p_synth` is `0.3` |
| `phased` | `warmup_turns` | Synth warmup followed by adversarial turns |
| `min_each` | `min_synth`, `min_adversarial`, `p_synth` | Guarantees each minimum, then fills by Bernoulli choice |
| `ramp` | `warmup_turns` | Synth warmup, then adversarial probability rises linearly to 1 |

`p_synth` must be in `[0, 1]`. The deprecated `synth_to_adversarial_ratio` is converted to a Bernoulli schedule with a warning.

## Adversarial scenarios and scoring

Adversarial scenarios may live inline in `scenario_catalog` or in `adversarial_scenario_catalog`. They require `scenario_id`, `scenario_type`, and `scenario_text`. Optional fields include `hijack_target`, `failure_threshold`, `fresh_start_after_refusals`, and `judge_overrides`.

An omitted scenario threshold resolves to `scoring.adversarial.failure_threshold` (default 3). `fresh_start_after_refusals: 0` disables automatic strategy rotation. `judge_overrides` is preserved in normalized contracts but is not currently applied; validation warns when it is present.

## Attack memory

`eval_plan.attack_memory` accepts:

- `shared`: one run-wide memory shared across personas.
- `per_persona`: isolated memory for each persona.
- `none`: no attack memory is recorded or written.

`attack_memory_max_entries` caps retained entries. `seed_attack_memory_path` accepts one path, a list, or a glob, but seeding is honored only in `shared` mode. On resume, restored run-state memory supersedes seed files.

## Trajectory configuration

Trajectory evaluation is opt-in:

```yaml
trajectory:
  enabled: true
  trace_field: trace
```

The target response may place its structured activity trace at `trace_field`. Empty or non-meaningful traces remain response-only and do not invoke the trace summarizer. See [unified evaluation](unified_evaluation.md#trajectory-evaluation) for behavior and [output artifacts](output_artifacts.md#unified-adversarial-score-fields) for persisted fields.

## Checked-in examples

The current examples are under `contracts/examples/`:

- `chatbot_test_contract.yaml` and `ten_k_conversations.yaml`: synth contracts.
- `unified_evaluation_demo.yaml`, `unified_evaluation_demo_local.yaml`, `tfsa_assistant.yaml`, `tfsa_one_week_traffic.yaml`, and `tfsa_testing.yaml`: general unified examples.
- `tfsa_aws_unified_evaluation_no_reasoning.yaml`, `tfsa_aws_unified_evaluation_reasoning.yaml`, and `wealth_advisory.yaml`: unified AgentCore/model examples.
- `browser_chatbot_test.yaml`: browser target example.
- `agent-runtime-logs-export.yaml`: AgentCore runtime-log export configuration used by supporting tooling.

Validate any contract with:

```bash
uv run ase validate-contract contracts/examples/unified_evaluation_demo.yaml
```
