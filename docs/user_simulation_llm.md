# User Simulation with an LLM

The `UserSimulator` uses an optional LLM to generate realistic persona-driven messages. It combines persona attributes, scenario intent, conversation history, configured failure modes, and persistent [persona memory](persona_memory.md). If no provider is configured or detected, it falls back to deterministic templates.

## Configure the simulator

Contract configuration makes the selected provider and model reproducible, but synth and
unified modes use different provider factories and therefore different provider names.
Do not copy provider aliases between these paths.

### Synth contracts

The optional top-level `llm` block configures the synth/legacy `LLMClient`:

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  max_tokens: 1024
  temperature: 0.7
  api_key_env: OPENAI_API_KEY
```

For Azure OpenAI in a synth contract, use the normalized synth client name
`azure_openai` (the aliases `azure` and `azureopenai` also normalize to it):

```yaml
llm:
  provider: azure_openai
  model: gpt-4o-mini
  api_key_env: AZURE_OPENAI_API_KEY
  azure:
    endpoint: "${AZURE_OPENAI_ENDPOINT}"
    deployment: "${AZURE_OPENAI_DEPLOYMENT}"
    api_version: "${AZURE_OPENAI_API_VERSION:-2024-12-01-preview}"
```

If synth `llm.provider` is omitted or empty, this client can auto-detect a provider from
the environment.

### Unified contracts

Unified contracts require a top-level `llm` specification. The user simulator inherits
that specification unless `components.user_simulator` overrides it. The unified factory
accepts exactly `mock`, `claude`, `openai`, `azure-openai`, `bedrock`, and `ollama`.

```yaml
llm:
  provider: azure-openai
  model: gpt-4o-mini
  azure:
    endpoint: "${AZURE_OPENAI_ENDPOINT}"
    deployment: "${AZURE_OPENAI_DEPLOYMENT}"
    api_version: "${AZURE_OPENAI_API_VERSION:-2024-12-01-preview}"

components:
  user_simulator:
    provider: claude
    model: claude-haiku-4-5-20251001
    api_key_env: ANTHROPIC_API_KEY
```

Unified native Bedrock uses `provider: bedrock`, the standard `boto3` credential chain,
and region precedence `bedrock.region` → `AWS_DEFAULT_REGION` → `us-east-1`. It does not
use the bearer-token Bedrock path described below for the synth/legacy client.

> **Unified Ollama limitation:** Ollama is real only for the unified user-simulator
> interface. The current unified factory silently uses the mock backend for ARE planner,
> generator, and judge calls. Adversarial results from a unified `provider: ollama` run
> are not Ollama-backed adversarial scores.

Copy `src/.env.example` to `src/.env` and set the referenced credentials. Keep secrets out of the contract. Corporate TLS/proxy and cloud authentication guidance belongs in [environment setup](environment_setup.md).

## Synth/legacy provider detection

The synth/legacy `LLMClient` supports these provider names and environment fallbacks:

| Provider | Explicit `provider` | Primary environment values |
| :--- | :--- | :--- |
| Azure OpenAI | `azure_openai` (aliases `azure`, `azureopenai`) | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY`, `MODEL_NAME` |
| OpenAI | `openai` | `OPENAI_API_KEY`, `MODEL_NAME` |
| Ollama | `ollama` | `OLLAMA_BASE_URL` or `OLLAMA_API_BASE`, `MODEL_NAME` |
| Bedrock OpenAI-compatible endpoint | `bedrock` | `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION`, optional `AWS_BEDROCK_ENDPOINT`, `MODEL_NAME` |

For credential indirection, `api_key_env` selects the environment variable containing the key/token. Provider defaults are `AZURE_OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `AWS_BEARER_TOKEN_BEDROCK`.

### Auto-detection order

When a synth contract does not specify a provider, the client checks in this order:

1. Azure OpenAI (`AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT`)
2. Anthropic (`ANTHROPIC_API_KEY`)
3. OpenAI (`OPENAI_API_KEY`)
4. Ollama (`OLLAMA_BASE_URL` or `OLLAMA_API_BASE`)
5. Bedrock (`AWS_BEARER_TOKEN_BEDROCK`)

An explicit synth contract provider takes precedence over auto-detection. Unified
contracts do not use this auto-detection path; their explicit `LLMSpec` is built by the
unified factory.

## Run a simulation

```bash
uv sync
uv run ase validate-contract contracts/examples/chatbot_test_contract.yaml
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
```

For this synth example, `--dry-run` mocks/disables the target call but does not force the
user simulator to mock mode. A configured simulator LLM can still be called. If no synth
provider is configured or detected, the simulator uses template messages. Use provider
configuration—not `--dry-run` alone—to determine whether synth generation makes an LLM
call. Unified dry-run differs: its runner forces harness component and LLM-target specs
to `mock` before building clients.

## Message generation and memory

On each synth turn, the simulator builds a prompt from:

- persona demographics and communication style;
- scenario intent, context, retrieval topics, and success criteria;
- recent user/assistant history;
- planned failure-injection modes;
- demographics, preferences, settings, summaries, and long-term recall loaded from the persona memory file.

The model is initialized lazily on the first LLM-backed turn. If `LLMResult.error` is set,
including for a content-filter block, `UserSimulator` logs a warning and emits its
deterministic fallback message for that turn. The simulator does not propagate a
structured error row to the runner for this condition.

## Troubleshooting

### `no_provider_configured`

The synth/legacy client had no explicit provider and none of its auto-detection variables were present. Add a synth `llm.provider` plus its provider settings, or configure one of the environment combinations above.

### `llm_disabled`

The synth/legacy client is disabled, so the simulator emits a template fallback. This
does not by itself indicate a credential failure, and synth `--dry-run` alone does not
disable an otherwise configured simulator provider.

### Azure authentication failure

For API-key authentication, verify the environment variable named by `api_key_env` (default `AZURE_OPENAI_API_KEY`). Managed identity settings (`AZURE_AUTH_TYPE`, optional `AZURE_CLIENT_ID`, and `AZURE_OPENAI_SCOPE`) apply to the synth/legacy client; the current unified Azure backend uses its API-key path.

### Ollama connection failure

Start the Ollama service and confirm its base URL. Unified mode reads the model from its explicit LLM spec and uses `OLLAMA_BASE_URL`; the synth/legacy client can fall back to `MODEL_NAME` and `OLLAMA_BASE_URL`/`OLLAMA_API_BASE`.

### TLS, proxy, AWS, or network errors

Use the platform-specific checks in [environment setup](environment_setup.md) rather than disabling verification without understanding the trust boundary.

## Related documentation

- [Contract reference](contracts.md) — schema, providers, target modes, and examples.
- [Persona memory](persona_memory.md) — persisted user context and lifecycle.
- [CLI guide](cli_usage.md) — validation and run commands.
- [Environment setup](environment_setup.md) — credentials, TLS, proxies, AWS, and network troubleshooting.
