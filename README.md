# Adaptive Synthetic Evaluation

A Python CLI tool for generating synthetic multi-turn chat histories to evaluate HR policy chatbots. This local-first, contract-driven simulation engine creates realistic conversation data without requiring production telemetry or external dependencies.

## 🎯 Overview

Adaptive Synthetic Eval helps you:
- **Generate realistic test data**: Create thousands of diverse, persona-driven conversations
- **Test chatbot behavior**: Validate responses across different user types, scenarios, and edge cases
- **Inject failures**: Simulate ambiguous queries, typos, frustration, and policy boundary pressure
- **Evaluate at scale**: Run concurrent simulations with configurable traffic patterns
- **Analyze results**: Export structured artifacts (JSONL, CSV, Markdown) for downstream analysis

### Key Features

✅ **Contract-driven configuration** - YAML-based contracts define personas, scenarios, and traffic mix  
✅ **LLM-powered user simulation** - Dynamic, context-aware message generation using Azure OpenAI, Ollama, Anthropic, or OpenAI  
✅ **Persistent persona memory** - Markdown-based memory system that evolves across conversations  
✅ **Real-time chat streaming** - Watch conversations unfold live in your terminal  
✅ **Interactive runtime controls** - Adjust speed, pause, change user behavior mid-run  
✅ **Failure injection** - Configurable ambiguity, missing information, typos, and frustration  
✅ **Local-first design** - No production telemetry or cloud dependencies required  
✅ **Dry-run mode** - Test contracts and workflows without calling external APIs  

## 📋 Table of Contents

- [Setup](#setup)
- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [LLM-Based User Simulation](#llm-based-user-simulation)
- [Persistent Persona Memory](#persistent-persona-memory)
- [CLI Commands](#cli-commands)
- [Output Artifacts](#output-artifacts)
- [Realtime Chat & Controls](#realtime-chat--controls)
- [Configuration Reference](#configuration-reference)
- [Testing](#testing)
- [Documentation](#documentation)
- [Troubleshooting](#troubleshooting)

## Setup

### Prerequisites

1. **Python 3.11+**
2. **uv package manager** (recommended)

#### Install uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Alternative via pip
pip install uv
```

> **Note**: If `uv` is not on your PATH, use `python -m uv` instead.
> For Windows OneDrive users experiencing hardlink errors, set `$env:UV_LINK_MODE='copy'`.

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
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --realtime-chat
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

5. **Command Shortcut**: The project exposes a shorthand entrypoint `ase`. Once you run `uv sync` in the workspace, you can execute the CLI via:
   ```bash
   uv run ase [COMMAND]
   ```
   
   To use the shortcut command directly from any directory without prefixing `uv run`, install it as a tool:
   ```bash
   uv tool install --editable .
   ```
   Now you can execute simply:
   ```bash
   ase [COMMAND]
   ```

### Corporate Environment Setup

If you're working behind a corporate proxy or firewall, you may need additional configuration:

#### SSL Certificate Configuration

Corporate networks often use custom SSL certificates for traffic inspection. To configure these:

1. **Obtain your corporate CA certificate** (usually provided by IT as a `.pem` or `.crt` file)

2. **Set environment variables** to trust the corporate certificate:

   **Linux/macOS (Bash/Zsh):**
   ```bash
   export REQUESTS_CA_BUNDLE=/path/to/your/corporate-ca.pem
   export SSL_CERT_FILE=/path/to/your/corporate-ca.pem
   export CURL_CA_BUNDLE=/path/to/your/corporate-ca.pem
   ```

   **Windows (PowerShell):**
   ```powershell
   $env:REQUESTS_CA_BUNDLE = "C:\path\to\your\corporate-ca.pem"
   $env:SSL_CERT_FILE = "C:\path\to\your\corporate-ca.pem"
   $env:CURL_CA_BUNDLE = "C:\path\to\your\corporate-ca.pem"
   ```

   **For Git operations:**
   ```bash
   git config --global http.sslCAInfo /path/to/your/corporate-ca.pem
   ```

#### Proxy Configuration

If your network requires authenticated proxy access:

**Linux/macOS (Bash/Zsh):**
```bash
export HTTP_PROXY="http://username:password@proxy.company.com:8080/"
export HTTPS_PROXY="http://username:password@proxy.company.com:8080/"
```

**Windows (PowerShell):**
```powershell
$env:HTTP_PROXY = "http://username:password@proxy.company.com:8080/"
$env:HTTPS_PROXY = "http://username:password@proxy.company.com:8080/"
```

> **Note:** If your username contains special characters (like backslashes in domain usernames), URL-encode them first:
> ```powershell
> $username = [uri]::EscapeDataString("DOMAIN\\username")
> $password = [uri]::EscapeDataString("your-password")
> $env:HTTP_PROXY = "http://${username}:${password}@proxy.company.com:8080/"
> ```

#### Persistent Configuration

To make these settings permanent:

- **Linux/macOS**: Add the `export` commands to your `~/.bashrc`, `~/.zshrc`, or shell profile
- **Windows**: Use System Properties → Advanced → Environment Variables, or PowerShell:
  ```powershell
  [System.Environment]::SetEnvironmentVariable('REQUESTS_CA_BUNDLE', 'C:\path\to\cert.pem', 'User')
  ```

#### Troubleshooting Corporate Network Issues

- **SSL errors**: Verify the CA certificate path is correct and the file exists
- **Connection timeouts**: Check proxy address and port with your IT department
- **Authentication failures**: Ensure username/password are correctly URL-encoded
- **uv sync fails**: Try setting `UV_HTTP_TIMEOUT=300` for longer timeout on slow connections

## Quick Start

### 1. Validate a Contract

```bash
uv run ase validate-contract contracts/examples/chatbot_test_contract.yaml
```

### 2. Run a Dry-Run Simulation

Test your contract without making real API calls:

```bash
uv run ase run \
  --contract contracts/examples/chatbot_test_contract.yaml \
  --dry-run
```

### 3. Generate Human-Readable Conversations

Export conversations in a readable format with Persona/Bot labels:

```bash
uv run ase run \
  --contract contracts/examples/chatbot_test_contract.yaml \
  --dry-run \
  --output-conversations
```

Output: `outputs/runs/<run_id>/conversations.txt`

### 4. Watch Realtime Chat (Single Persona Only)

Stream conversations live in your terminal:

```bash
uv run ase run \
  --contract contracts/examples/chatbot_test_contract.yaml \
  --realtime-chat
```

> **Note**: Realtime chat only works when `persona_pool` has exactly one persona.

### 5. Summarize Previous Runs

```bash
uv run ase summarize --run-id chatbot_test_run
```

Outputs are written under `outputs/runs/<run_id>/`.

## Core Concepts

### Contracts

Contracts are YAML files that define your simulation configuration. They specify:

- **Personas**: User profiles with demographics, communication styles, and HR familiarity
- **Scenarios**: Conversation topics with failure injection parameters
- **Traffic Mix**: How personas and scenarios combine, concurrency, and batch sizes
- **Time Window**: Synthetic days and compressed runtime duration
- **Output Configuration**: Where to save results and run identifiers

Example contract structure:
```yaml
simulation_suite:
  suite_id: my_test_suite
  target_application: hr_chatbot
  
persona_pool:
  - persona_id: P1
    role: new_employee
    location: Toronto
    seniority: junior
    communication_style: polite
    hr_familiarity: low

scenario_catalog:
  - scenario_id: S1
    domain: parental_leave
    intent: understand_eligibility
    failure_injection:
      ambiguity: 0.2
      typos: 0.1

traffic_orchestration:
  total_conversations: 100
  conversation_turns:
    min: 3
    max: 7
  mix:
    - persona_id: P1
      scenario_id: S1
      weight: 1.0
```

See [`contracts/examples/`](./contracts/examples) for complete examples.

### Personas

Personas represent different user types interacting with your chatbot. Each persona has:

- **Demographics**: Role, location, seniority level
- **Behavioral Traits**: Communication style (direct, polite, anxious), HR familiarity
- **Memory State**: Persistent markdown file tracking preferences, settings, and conversation history
- **Privacy Sensitivity**: How cautious they are about sharing personal information

### Scenarios

Scenarios define conversation topics and inject realistic challenges:

- **Domain**: HR policy area (parental leave, benefits, performance reviews)
- **Intent**: What the user wants to accomplish
- **Failure Injection**:
  - `ambiguity`: Vague or unclear questions
  - `missing_information`: Incomplete context
  - `typos`: Spelling errors and grammatical mistakes
  - `frustration`: Emotional escalation
  - `policy_boundary_pressure`: Edge cases testing policy limits

### Traffic Orchestration

Controls how conversations are generated:

- **Total Conversations**: Number of unique chat sessions
- **Turn Range**: Min/max turns per conversation
- **Mix**: Weighted combinations of personas and scenarios
- **Concurrency**: Parallel conversation generation
- **Batch Size**: How many conversations to generate at once

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
   uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
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
   uv run ase run --contract contracts/examples/one_week_chat_history.yaml --dry-run
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
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
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

## Persistent Persona Memory

The simulation engine includes a persistent, isolated markdown-based memory system for each persona to emulate human memory retention across runs and conversation threads.

- **Markdown Storage**: Saves persona state (Demographics, Preferences, Settings, Summary Notes, Long Term Recall, and Recent Window) in `outputs/runs/<run_id>/personas/<persona_id>_memory.md`.
- **Dynamic Profile Deltas**: Automatically extracts profile updates (such as language settings, custom preferences, and contact details) from chat logs using regex patterns.
- **Context Injection**: Prepend the active memory state directly into the LLM system prompt for context-aware conversations.
- **Thread Safety**: Uses atomic file swaps and path-level locks to support high concurrency safely.

For full architectural details, see the [Persona Memory Guide](./docs/persona_memory.md).

## CLI Commands

### validate-contract

Validate a simulation contract file:

```bash
uv run ase validate-contract <contract-file.yaml>
```

**Example**:
```bash
uv run ase validate-contract contracts/examples/chatbot_test_contract.yaml
```

### run

Execute a simulation run:

```bash
uv run ase run --contract <contract-file.yaml> [OPTIONS]
```

**Options**:
- `--contract`: Path to YAML/JSON contract file (required)
- `--dry-run`: Skip real chatbot calls, use mock responses
- `--output-conversations`: Generate human-readable conversations.txt
- `--realtime-chat`: Stream conversations live in terminal (single-persona only)
- `--interactive-realtime-controls`: Enable runtime controls (default: on with --realtime-chat)
- `--no-interactive-realtime-controls`: Disable runtime controls

**Examples**:
```bash
# Dry run
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run

# Real run with realtime chat
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat

# Export readable conversations
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --output-conversations
```

### summarize

Print run summary for a previous run:

```bash
uv run ase summarize --run-id <run-id> [--output-dir outputs]
```

**Example**:
```bash
uv run ase summarize --run-id chatbot_test_run
```

## Output Artifacts

Each run generates the following files in `outputs/runs/<run_id>/`:

| File | Description |
|------|-------------|
| `chat_history.jsonl` | Full chat history in JSON Lines format |
| `chat_history.csv` | Chat history in CSV format for spreadsheet analysis |
| `run_plan.json` | Detailed execution plan with persona/scenario assignments |
| `conversations.jsonl` | Structured conversation data with turns and metadata |
| `turns.jsonl` | Individual turn-level data with scores and annotations |
| `scores.jsonl` | Quality scores for each response (relevance, safety, grounding) |
| `run_summary.json` | High-level summary statistics and metrics |
| `generation_report.md` | Markdown report with run details and insights |
| `conversations.txt` | Human-readable conversations (with `--output-conversations`) |
| `personas/<id>_memory.md` | Persistent memory state for each persona |
| `contract.normalized.json` | Normalized contract used for the run |

### Example Output Structure

```
outputs/runs/chatbot_test_run/
├── chat_history.jsonl
├── chat_history.csv
├── conversations.jsonl
├── conversations.txt          # if --output-conversations
├── turns.jsonl
├── scores.jsonl
├── run_summary.json
├── run_plan.json
├── generation_report.md
├── contract.normalized.json
└── personas/
    └── TEST_P1_memory.md
```

## Realtime Chat & Controls

The `--realtime-chat` flag streams conversation turns directly in your terminal, providing a Claude Code / Copilot CLI-style experience. This feature is only available when `persona_pool` has exactly one persona.

### Interactive Runtime Controls

When realtime chat is enabled, you get an ephemeral command prompt (`realtime>`) that stays stable while conversation logs scroll above it. Use these commands to control the simulation:

| Command | Alias | Description |
|---------|-------|-------------|
| `help` | `h` | Show all available controls |
| `status` | `s` | Show current delay and mode |
| `faster` | `+` | Speed up playback |
| `slower` | `-` | Slow down playback |
| `pause` | `p` | Toggle pause/resume |
| `stop` | `q` | Stop the run early |
| `style <mode>` | - | Change user behavior for upcoming turns |

### Behavior Modes

Change how the persona behaves mid-conversation:

- `default` - Normal conversation style
- `aggressive` - Direct, demanding tone
- `polite` - Courteous and formal
- `concise` - Brief, to-the-point messages
- `confused` - Uncertain, asking clarifying questions
- `anxious` - Worried, seeking reassurance

**Examples**:
```bash
# While the run is active, type:
style aggressive
style polite
style default
```

### Usage

```bash
# Enable realtime chat with interactive controls (default)
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat

# Disable interactive controls
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat --no-interactive-realtime-controls
```

> **Note**: Controls are ephemeral—they only exist during the active run. When the run completes or you stop it, the input prompt is removed automatically.

## Documentation

Comprehensive guides are available in the [`docs/`](./docs) directory:

- [**Contract Specification**](./docs/contracts.md) - Detailed contract schema and configuration options
- [**CLI Usage Guide**](./docs/cli_usage.md) - Complete CLI reference and examples
- [**Persona Memory System**](./docs/persona_memory.md) - How persona memory works and persists across runs
- [**LLM User Simulation**](./docs/user_simulation_llm.md) - Setting up and configuring LLM providers
- [**Failure Injection**](./docs/failure_injection.md) - Configuring ambiguity, typos, frustration, and edge cases
- [**Chat History Schema**](./docs/chat_history_schema.md) - Output format specifications
- [**Adversarial Agent Review**](./docs/adversarial_agent_review.md) - Security and robustness testing
- [**Team Handoff Guide**](./docs/team_handoff.md) - Onboarding and collaboration tips

## Testing

### Run All Tests

```bash
uv run pytest -q
```

### Run Specific Test Suites

```bash
# Chatbot client tests
uv run pytest tests/unit/test_chatbot_client.py -v

# Contract validation tests
uv run pytest tests/unit/test_contract.py -v

# Generation tests
uv run pytest tests/unit/test_generation.py -v

# Integration tests
uv run pytest tests/integration/ -v
```

### Test Coverage

```bash
uv run pytest --cov=adaptive_synth_eval --cov-report=html
```

View coverage report in `htmlcov/index.html`.

## Troubleshooting

### Common Issues

#### 1. Module Not Found Errors

**Error**: `ModuleNotFoundError: No module named 'adaptive_synth_eval'`

**Solution**:
```bash
# Ensure you're in the project root
cd /path/to/adaptive-synth-eval

# Reinstall dependencies
uv sync --reinstall

# If running directly, set PYTHONPATH
export PYTHONPATH=src
```

#### 2. LLM Provider Configuration

**Error**: `no_provider_configured`

**Solution**: Verify your `src/.env` file has the correct variables for at least one provider:
- Ollama: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`
- Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL`

#### 3. Ollama Connection Refused

**Error**: `Connection refused` when using Ollama

**Solution**:
```bash
# Start Ollama service
ollama serve

# Verify it's running
curl http://localhost:11434/api/tags

# Check model is pulled
ollama list
```

#### 4. SSL Certificate Errors (Corporate Networks)

**Error**: `SSL: CERTIFICATE_VERIFY_FAILED`

**Solution**: Set corporate CA certificate:
```bash
export REQUESTS_CA_BUNDLE=/path/to/corporate-ca.pem
export SSL_CERT_FILE=/path/to/corporate-ca.pem
```

#### 5. uv Hardlink Errors on Windows OneDrive

**Error**: `os error 396` or hardlink failures

**Solution**:
```powershell
$env:UV_LINK_MODE='copy'
uv run ase run --contract ... --dry-run
```

Persist permanently:
```powershell
[System.Environment]::SetEnvironmentVariable('UV_LINK_MODE', 'copy', 'User')
```

#### 6. Realtime Chat Not Working

**Issue**: `--realtime-chat` doesn't stream output

**Cause**: Only works with single-persona contracts

**Solution**: Ensure your contract has exactly one persona in `persona_pool`:
```yaml
persona_pool:
  - persona_id: TEST_P1  # Only one persona
    role: tester
    ...
```

#### 7. Slow Performance

**Issue**: Simulation runs very slowly

**Solutions**:
- Use `--dry-run` to skip real API calls during testing
- Reduce `max_concurrency` in traffic orchestration
- Use local Ollama instead of cloud providers for faster iteration
- Increase batch size for better throughput

### Debug Mode

Enable debug logging for detailed troubleshooting:

```bash
export LOG_LEVEL=DEBUG
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
```

Look for informative log messages like:
```
INFO: Using Ollama model: qwen3.6:35b-a3b
INFO: Generated turn 1 with LLM provider: ollama
DEBUG: Request payload: {...}
```

### Getting Help

If you encounter issues not covered here:

1. Check the [documentation](./docs) directory for detailed guides
2. Review example contracts in [`contracts/examples/`](./contracts/examples)
3. Examine test files for usage patterns
4. Enable `LOG_LEVEL=DEBUG` and review logs

## Project Structure

```
adaptive-synth-eval/
├── contracts/examples/          # Example simulation contracts
│   ├── chatbot_test_contract.yaml
│   ├── one_week_chat_history.yaml
│   └── ten_k_conversations.yaml
├── docs/                        # Detailed documentation
│   ├── contracts.md
│   ├── cli_usage.md
│   ├── persona_memory.md
│   └── ...
├── outputs/runs/                # Generated simulation outputs
│   └── <run_id>/
│       ├── chat_history.jsonl
│       ├── conversations.jsonl
│       ├── run_summary.json
│       └── ...
├── src/adaptive_synth_eval/     # Main source code
│   ├── clients/                 # API clients (chatbot, LLM)
│   │   ├── chatbot.py
│   │   ├── llm.py
│   │   └── retry_utils.py
│   ├── config/                  # Configuration and contract parsing
│   │   ├── contract.py
│   │   └── schemas.py
│   ├── engines/                 # Core simulation engines
│   │   ├── chat_history_simulation.py
│   │   └── realtime_controls.py
│   ├── generation/              # Content generation modules
│   │   ├── personas.py
│   │   ├── scenarios.py
│   │   ├── turns.py
│   │   └── traffic.py
│   ├── scoring/                 # Response quality scoring
│   │   ├── response_quality.py
│   │   └── failure_modes.py
│   ├── artifacts/               # Output exporters and schemas
│   │   ├── exporters.py
│   │   └── schemas.py
│   └── cli.py                   # CLI entry point
├── tests/                       # Test suite
│   ├── unit/                    # Unit tests
│   └── integration/             # Integration tests
├── pyproject.toml               # Project configuration
└── README.md                    # This file
```

### Key Modules

- **`clients/`**: HTTP clients for chatbot APIs and LLM providers (Azure OpenAI, Ollama, Anthropic, OpenAI)
- **`config/`**: Contract validation, normalization, and schema definitions
- **`engines/`**: Core simulation logic including chat history generation and realtime controls
- **`generation/`**: Persona creation, scenario generation, turn synthesis, and traffic orchestration
- **`scoring/`**: Quality metrics for evaluating chatbot responses (relevance, safety, grounding)
- **`artifacts/`**: Export formats (JSONL, CSV, Markdown) and data schemas

## Contributing

### Development Workflow

1. **Fork and clone** the repository
2. **Create a feature branch**: `git checkout -b feature/my-feature`
3. **Make changes** and write tests
4. **Run tests**: `uv run pytest -q`
5. **Commit changes**: `git commit -am 'Add feature'`
6. **Push and create PR**

### Code Style

- Follow PEP 8 guidelines
- Use type hints where applicable
- Write docstrings for public functions and classes
- Keep functions focused and testable

### Adding New Features

1. Update or create contracts in `contracts/examples/`
2. Implement feature in appropriate module under `src/adaptive_synth_eval/`
3. Add unit tests in `tests/unit/`
4. Update documentation in `docs/` if needed
5. Update this README if user-facing changes

## Support

For questions, issues, or feature requests:

1. Review the [documentation](./docs)
2. Check existing issues and pull requests
3. Contact the development team
