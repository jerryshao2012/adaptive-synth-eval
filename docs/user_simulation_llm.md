# User Simulation with LLM Configuration

## Overview

The adaptive-synth-eval system uses LLMs to generate realistic user messages during chat simulation. This allows for more natural and varied conversation flows compared to template-based approaches.

## How It Works

When you configure an LLM provider, the `UserSimulator` automatically uses it to generate contextually appropriate user messages based on:
- **Persona attributes** (role, location, seniority, communication style)
- **Scenario intent** (what the user wants to accomplish)
- **Conversation history** (previous turns in the dialogue)
- **Failure injection modes** (typos, ambiguity, frustration, etc.)
- **Persona memory** (persistent demographics, preferences, and long-term recall from prior conversations; see the [Persona Memory Guide](file:///Users/jerryshao/Documents/projects/IBM/ai/adaptive-synth-eval/docs/persona_memory.md))

If no LLM is configured, the system falls back to deterministic template messages.

## Configuration

### Step 1: Choose Your LLM Provider

Copy `src/.env.example` to `src/.env` and configure ONE of the following providers:

#### Option 1: Azure OpenAI (Recommended for Enterprise)

```bash
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_KEY=your_azure_openai_api_key_here
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

For Managed Identity authentication (no API key):
```bash
AZURE_AUTH_TYPE=managed_identity
AZURE_CLIENT_ID=your_managed_identity_client_id
AZURE_OPENAI_SCOPE=https://cognitiveservices.azure.com/.default
```

#### Option 2: Anthropic Claude

```bash
ANTHROPIC_API_KEY=your_anthropic_api_key_here
MODEL_NAME=claude-sonnet-4-5-20250929
```

#### Option 3: OpenAI

```bash
OPENAI_API_KEY=your_openai_api_key_here
MODEL_NAME=gpt-4o-mini
```

#### Option 4: Ollama (Local Models - Free)

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3.6:35b-a3b
```

First install Ollama and pull a model:
```bash
ollama pull qwen3.6:35b-a3b
```

### Step 2: Install Dependencies

```bash
cd /Users/jerryshao/Documents/projects/IBM/ai/adaptive-synth-eval
uv sync
```

This installs:
- `langchain` - Unified LLM interface
- `langchain-openai` - OpenAI/Azure OpenAI support
- `langchain-anthropic` - Anthropic Claude support
- `langchain-ollama` - Ollama support
- `azure-identity` - Azure Managed Identity support
- `httpx` - HTTP client with SSL control
- `pydantic` - Data validation

### Step 3: Run Simulation

```bash
# Dry-run mode (generates user messages without calling chatbot)
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run

# Full simulation (calls both user simulation LLM and target chatbot)
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml
```

## Auto-Detection

The system automatically detects which LLM provider to use based on environment variables:

1. **Azure OpenAI**: Checks for `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT`
2. **Anthropic**: Checks for `ANTHROPIC_API_KEY`
3. **OpenAI**: Checks for `OPENAI_API_KEY`
4. **Ollama**: Checks for `OLLAMA_BASE_URL`

Priority order: Azure → Anthropic → OpenAI → Ollama

You can also explicitly specify a provider:
```python
from adaptive_synth_eval.clients.llm import LLMClient

client = LLMClient(enabled=True, model_provider="anthropic")
```

## SSL Configuration

For corporate environments with TLS interception:

```bash
VERIFY_SSL=false
SSL_CERT_FILE=/path/to/corporate-ca-bundle.pem
```

## Example Output

With LLM enabled, generated user messages look like:

```
Turn 1: "Hi there! I'm a new employee starting next week in Toronto. I heard we have parental leave benefits but I'm not sure how they work. Can you help me understand what I'm eligible for?"

Turn 2: "That makes sense, but I'm a bit confused about the timeline. If my partner gives birth in March, when exactly can I start my leave? And do I need to apply before or after the birth?"

Turn 3: "Thanks for clarifying! One more thing - I work remotely from Canada but our office is in the US. Which country's policies apply to me?"
```

Without LLM (fallback templates):

```
Turn 1: "Hi, I need help with parental_leave_policy. I want to understand_eligibility."
Turn 2: "Follow-up 2: can you clarify how this applies to someone in Canada?"
Turn 3: "Thanks. Can you summarize what I should do next?"
```

## Troubleshooting

### Error: "no_provider_configured"

**Cause**: No LLM provider environment variables are set.

**Solution**: Configure one of the providers in your `.env` file as shown above.

### Error: "llm_disabled"

**Cause**: The LLM client is disabled (this is normal in dry-run mode if no provider is configured).

**Solution**: Set up an LLM provider or accept template-based fallback messages.

### Error: Import errors for langchain packages

**Cause**: Dependencies not installed.

**Solution**: Run `uv sync` to install all required packages.

### Error: Azure authentication failures

**Cause**: Missing or incorrect API key / Managed Identity configuration.

**Solution**: 
- For API key auth: Verify `AZURE_OPENAI_API_KEY` is correct
- For Managed Identity: Ensure `AZURE_AUTH_TYPE=managed_identity` and `AZURE_CLIENT_ID` is set

### Error: Connection refused (Ollama)

**Cause**: Ollama service not running.

**Solution**: Start Ollama with `ollama serve` and ensure the model is pulled.

## Performance Considerations

- **Temperature**: Set to 0.7 for balanced creativity vs. consistency
- **Latency**: Local models (Ollama) are fastest; cloud models add network latency
- **Cost**: Each conversation turn costs tokens; monitor usage with cloud providers
- **Concurrency**: The simulation engine respects `max_concurrency` settings to avoid rate limits

## Advanced Usage

### Custom Model Parameters

You can modify the temperature and other parameters in `src/adaptive_synth_eval/clients/llm.py`:

```python
self._model = AzureChatOpenAI(
    # ... other params ...
    temperature=0.7,  # Adjust for more/less variability
    max_tokens=500,   # Limit response length
)
```

### Explicit Provider Selection

Override auto-detection by passing `model_provider` parameter:

```python
from adaptive_synth_eval.generation.turns import UserSimulator

simulator = UserSimulator(persona, scenario, turn_count=5)
simulator.llm_client = LLMClient(enabled=True, model_provider="ollama")
```

### Logging

Enable debug logging to see LLM interactions:

```bash
export LOG_LEVEL=DEBUG
uv run ase run --contract your_contract.yaml
```

## Architecture Reference

The implementation follows the pattern from `/Users/jerryshao/Documents/projects/IBM/ai/deepagents-demo/deep_research/model_factory.py`:

- **Lazy initialization**: Models are created only when first needed
- **Provider abstraction**: Unified interface across different LLM vendors
- **Environment-driven**: All configuration via environment variables
- **Error resilience**: Graceful fallback to templates when LLM unavailable
- **Rate limiting**: Built-in retry logic with exponential backoff

## Next Steps

1. Configure your preferred LLM provider in `src/.env`
2. Run a small test: `uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run`
3. Inspect generated conversations in `outputs/runs/chatbot_test_run/conversations.jsonl`
4. Scale up to full simulations once satisfied with message quality
