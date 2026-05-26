# Adaptive Synthetic Eval

Python CLI for generating synthetic multi-turn ChatHistory data for an HR policy chatbot.

The active implementation is intentionally local-first:

- No production telemetry dependency
- No Azure AI Evaluation Simulator dependency
- No chatbot tool-call requirement
- Contract-driven personas, scenarios, traffic mix, synthetic days, and failure injection

## Setup

### Prerequisites: Install uv Package Manager

Install [uv](https://docs.astral.sh/uv/) package manager:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

*Alternative installation for restricted corporate environments:*
```bash
pip install uv
```

*If `uv` is not available on your system path, you can try:*
```bash
uv sync
# In Windows if PATH is not setup properly
python -m uv sync
```

Note: use `uv sync --reinstall` to reinstall all packages if you see some errors.

If your workspace is inside OneDrive on Windows and `uv run` fails with hardlink errors (for example `os error 396`), run commands with copy mode:

```powershell
$env:UV_LINK_MODE='copy'
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --realtime-chat
```

You can also persist this for your user profile:

```powershell
[System.Environment]::SetEnvironmentVariable('UV_LINK_MODE', 'copy', 'User')
```

### Project Setup

1. Copy the example environment file and configure your settings:
   ```bash
   cp src/.env.example src/.env
   ```

2. Edit `src/.env` and fill in your actual values (especially API keys and endpoints).

3. **Important**: Never commit `src/.env` files with real credentials to version control.

4. If running the CLI directly from a local checkout and Python cannot find the package, set `PYTHONPATH` to include the `src` directory:
   ```bash
   export PYTHONPATH=src
   ```

   This is useful for local development because the project uses a `src/` layout, where the importable package lives under `src/adaptive_synth_eval`.

## Quick Start

```bash
# Validate the one week history contract
uv run adaptive-synth-eval validate-contract contracts/examples/one_week_chat_history.yaml

# Run the simulation in dry-run mode
uv run adaptive-synth-eval run --contract contracts/examples/one_week_chat_history.yaml --dry-run

# Run a dedicated chatbot unit test contract
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run

# Output conversations in human-readable format (with Human/Bot labels)
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --output-conversations

# Stream simulated Human/Bot chat live in console (single-persona contracts)
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --realtime-chat

# Summarize a previous run
uv run adaptive-synth-eval summarize --run-id one_week_chat_history
```

Outputs are written under `outputs/runs/<run_id>/`.

## LLM-Based User Simulation

The simulation engine supports both template-based message generation and dynamic, LLM-driven user simulation. When an LLM provider is configured, the simulator automatically uses it to generate contextual, persona-aware user messages that adapt to the conversation history.

### Quick Start (Ollama - Free & Local)

1. **Install Ollama**:
   ```bash
   brew install ollama  # macOS, or download from https://ollama.ai
   ```

2. **Pull a Model**:
   ```bash
   ollama pull qwen3.6:35b-a3b  # or glm-4.7-flash, etc.
   ```

3. **Configure Environment**:
   Ensure `src/.env` contains:
   ```env
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=qwen3.6:35b-a3b
   ```

4. **Install Dependencies & Start Service**:
   ```bash
   uv sync
   ollama serve  # Keep running in a separate terminal
   ```

5. **Run Test Simulation**:
   ```bash
   uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
   ```

### Enterprise Setup (Azure OpenAI)

1. **Configure Environment**:
   Ensure `src/.env` contains:
   ```env
   AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
   AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
   AZURE_OPENAI_API_KEY=your-key-here
   AZURE_OPENAI_API_VERSION=2024-12-01-preview
   ```

2. **Run Simulation**:
   ```bash
   uv run adaptive-synth-eval run --contract contracts/examples/one_week_chat_history.yaml --dry-run
   ```

### Verify It's Working

Check for LLM-generated messages in the output conversations:
```bash
# Look for natural language, not templates
grep "persona_role" outputs/runs/*/conversations.jsonl
```

**Good (LLM-enabled)**:
```json
{"user_message": "Hi! I'm new to the company and trying to understand my parental leave options...", ...}
```

**Fallback (Template-based)**:
```json
{"user_message": "Hi, I need help with parental_leave_policy. I want to understand_eligibility.", ...}
```

Or enable debug logging to check the provider output:
```bash
export LOG_LEVEL=DEBUG
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
```
Look for lines like:
```
INFO: Using Ollama model: glm-4.7-flash:latest
INFO: Generated turn 1 with LLM provider: ollama
```

### Example Comparison

| Without LLM (Template-based) | With LLM (Contextual & Persona-aware) |
|---|---|
| **Turn 1**: "Hi, I need help with parental_leave_policy. I want to understand_eligibility." | **Turn 1**: "Hello! I'm starting my new role next month in Toronto and I've been reading about the parental leave benefits. Could you explain what I'm eligible for as a new employee?" |
| **Turn 2**: "Follow-up 2: can you clarify how this applies to someone in Canada?" | **Turn 2**: "That's helpful, but I'm wondering about the timing. My partner is due in March - can I start my leave before the birth, or does it have to be after? And do I need to give advance notice?" |
| **Turn 3**: "Thanks. Can you summarize what I should do next?" | **Turn 3**: "One last question - since I'll be working remotely from Canada but our headquarters is in the US, which country's parental leave policies apply to my situation?" |

### Cost & Performance Considerations

| Provider | Cost per 1K turns | Latency | Setup Complexity |
|----------|------------------|---------|------------------|
| Ollama (local) | $0 | ~1-3s | Easy |
| Azure GPT-4o-mini | ~$0.05 | ~2-5s | Medium |
| Anthropic Claude | ~$0.10 | ~2-5s | Easy |
| OpenAI GPT-4o-mini | ~$0.05 | ~2-5s | Easy |

For 50,000 turns (e.g., 10,000 conversations × 5 turns):
- **Ollama**: Free
- **Cloud providers**: ~$2.50-$5.00

### Implementation Summary & Architecture

The LLM-based user simulation is powered by the following components:

1. **LLM Client (`src/adaptive_synth_eval/clients/llm.py`)**:
   - Supports Azure OpenAI (via API key or Managed Identity), Anthropic Claude, OpenAI GPT, and Ollama.
   - Detects available providers from environment variables automatically.
   - Uses lazy initialization, rate-limiting retry logic, and supports custom SSL verification for corporate environments.
2. **User Simulator (`src/adaptive_synth_eval/generation/turns.py`)**:
   - Automatically uses the LLM client if configured; falls back gracefully to templates otherwise.
3. **Configuration**:
   - Managed via `src/.env` (see `src/.env.example` for details).

### Troubleshooting

- **"No module named 'langchain'"**: Run `uv sync` to install the dependencies (`langchain`, `langchain-openai`, `langchain-anthropic`, `langchain-ollama`).
- **"Connection refused" (Ollama)**: Ensure the Ollama service is running via `ollama serve`, and test connectivity with `curl http://localhost:11434/api/tags`.
- **"no_provider_configured"**: Double check that your `src/.env` file contains the correct environment variables for either Ollama (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`) or your cloud provider.

## Main Artifacts


- `chat_history.jsonl`
- `chat_history.csv`
- `run_plan.json`
- `conversations.jsonl`
- `turns.jsonl`
- `scores.jsonl`
- `run_summary.json`
- `generation_report.md`
- `conversations.txt` (when using `--output-conversations` flag)

`--realtime-chat` streams conversation turns directly in the terminal and is enabled only when `persona_pool` has exactly one persona. For multi-persona contracts, the run continues and live output is skipped.

## Tests

Run all unit tests:
```bash
uv run pytest -q
```

Run specific chatbot client tests:
```bash
uv run pytest tests/unit/test_chatbot_client.py -v
```
