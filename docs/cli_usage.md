# CLI Usage

For convenience, you can use the shorthand command `ase` instead of the full `adaptive-synth-eval` command.

## Installation & Setup

### Running with uv
Ensure dependencies and the local package are installed in editable mode first:
```bash
uv sync
uv pip install -e .
```

Then prefix commands with `uv run ase`:
```bash
uv run ase validate-contract contracts/examples/tfsa_one_week_traffic.yaml
```

### Running Globally (No `uv run` prefix)
You can install the tool globally so that `ase` is available in your PATH from any directory:
```bash
uv tool install --editable .
```
Then, you can run commands directly:
```bash
ase validate-contract contracts/examples/tfsa_one_week_traffic.yaml
```

---

## Commands & Examples

### Validating a Contract
Validate a contract to ensure it matches the schema and is configurationally sound:
```bash
uv run ase validate-contract contracts/examples/tfsa_one_week_traffic.yaml
```

### Running Simulations
The `run` command executes simulation sessions based on a contract.

#### Dry-Run Execution
Generate one week of dry-run `ChatHistory`:
```bash
uv run ase run --contract contracts/examples/tfsa_one_week_traffic.yaml --dry-run
```

Generate a 10,000-conversation dataset:
```bash
uv run ase run --contract contracts/examples/ten_k_conversations.yaml --dry-run
```

Run a focused chatbot unit test:
```bash
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
```

#### Outputting Conversations
Output conversations in a human-readable format (with Persona/Bot labels):
```bash
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --output-conversations
```
This generates a `conversations.txt` file in the output directory with each conversation formatted as:
- Conversation metadata (ID, session, persona, scenario, synthetic day)
- Alternating "Persona (Turn N):" and "Bot (Turn N):" messages
- Error indicators if any occurred

See [docs/example_conversations_output.txt](example_conversations_output.txt) for a sample output.

### Unified-Only Options (Unified Contracts Only)
The following options are valid only when running with a unified contract. If passed with a synthetic-only contract, the CLI will return a `ContractError` (exit code 2):
- `--scenario <id>`: Filter the run to only a specific synthetic scenario ID.
- `--adversarial-scenario <id>`: Filter the run to only a specific adversarial scenario ID.
- `--max-concurrency <n>`: Override the `eval_plan.max_concurrency` config for this run.
- `--run-id <id>`: Explicitly override the output run ID.

### Incomplete Run Recovery
When an existing run directory appears incomplete (for example, a previous run was interrupted), the CLI can resume or restart safely.

- `--incomplete-run-action ask|resume|restart|abort`:
  - `ask` (default): Prompt interactively to choose resume, restart, or abort.
  - `resume`: Continue only remaining conversations from checkpoint state.
  - `restart`: Delete the existing run directory and start a fresh run.
  - `abort`: Stop immediately and return without running.

Examples:

```bash
# Resume an interrupted run using existing artifacts/checkpoints
uv run ase run --contract contracts/examples/tfsa_one_week_traffic.yaml --incomplete-run-action resume

# Start a fresh run and clean previous artifacts for this run_id
uv run ase run --contract contracts/examples/tfsa_one_week_traffic.yaml --incomplete-run-action restart
```

Notes:
- In non-interactive environments (no TTY), `ask` is not allowed for incomplete runs. Use `resume`, `restart`, or `abort` explicitly.
- Checkpoint state is persisted in `outputs/runs/<run_id>/run_state.json`.

### Summarizing a Run
Summarize a run's results:
```bash
uv run ase summarize --run-id one_week_chat_history
```

---

## Loop Engineering (Continuous Evaluation)

Run adaptive evaluation loops that continuously discover targets, apply constrained recoveries, and run unattended with safety guardrails. See [docs/loop_engineering_for_adversarial_adaptive_synthetic_evaluation.md](loop_engineering_for_adversarial_adaptive_synthetic_evaluation.md) for architecture and [docs/loop_operations_runbook.md](./loop_operations_runbook.md) for operations.

### Loop Commands

#### Initialize Loop Assets
```bash
uv run ase loop init --profile <id> --profiles-dir loops/profiles --output-dir outputs
```

#### Run a Single Loop Cycle
```bash
uv run ase loop run --profile <id> --profiles-dir loops/profiles --output-dir outputs
```

#### Start a Recurring Loop (Single Profile)
```bash
uv run ase loop start --profile <id> --profiles-dir loops/profiles --output-dir outputs
```

#### Start All Checked-In Loops (Multi-Profile Coordination)
```bash
uv run ase loop start --all --profiles-dir loops/profiles --output-dir outputs
```

#### Check Loop Status
```bash
uv run ase loop status --profile <id> --profiles-dir loops/profiles --output-dir outputs
```

#### Audit Loop Readiness
```bash
uv run ase loop audit --profile <id> --profiles-dir loops/profiles --output-dir outputs
```

#### Pause a Loop (Kill Switch)
```bash
uv run ase loop pause --profile <id> --reason "maintenance" --profiles-dir loops/profiles --output-dir outputs
```

#### Resume a Paused Loop
```bash
uv run ase loop resume --profile <id> --profiles-dir loops/profiles --output-dir outputs
```

### Loop Profiles
Loop profiles are stored under `loops/profiles/*.yaml` and declare:
- `readiness_level` (`L1|L2|L3`)
- `cadence` (cron or interval)
- `targets` (contract paths to evaluate)
- `checker_policy` (retry limits, auto-pause thresholds)
- `llm_config` (Azure OpenAI, AWS Bedrock, Ollama for AI reasoning)

Example: `loops/profiles/unified_regression_guard.yaml`

### Loop Runtime Artifacts
Loop state is persisted under `outputs/loops/`:
- `STATE.md`: Human-readable loop status and inbox
- `loop-budget.md`: Run/token budget snapshots
- `loop-run-log.md`: Append-only event history
- `state/<profile_id>.json`: Machine-readable loop state

---

## Real-Time Chat & Interactive Controls

Stream Persona/Bot chat to the console in real time:
```bash
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat
```

Disable interactive runtime controls during realtime chat (controls are enabled by default with `--realtime-chat`):
```bash
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat --no-interactive-realtime-controls
```

### How `--realtime-chat` Works
- It is opt-in and streams conversations directly in the console as alternating Human and Assistant panels.
- In unified mode, it supports concurrent conversations and respects `max_concurrency`.
- With `--persona <id>`, realtime mode runs a single conversation (`effective_max_concurrency = 1`).
- It does not replace output artifacts; files like `chat_history.jsonl` and `conversations.txt` (when enabled) are still generated normally.

### How `--persona <id>` Works
- Limit the terminal simulation session to a single specific persona ID.
- Useful for running multiple terminals in parallel targeting different personas.
- Automatically disables realtime session controls (`list` and `switch`).

### How Interactive Realtime Controls Work
- They are enabled by default when `--realtime-chat` is enabled.
- Use `--no-interactive-realtime-controls` to turn them off.
- During the run, type a command and press Enter to control playback.
- Offers interactive auto-hinting / auto-completion of commands and arguments as you type.
- In multi-persona mode, the prompt displays active persona+conversation (e.g., `⚡> [P001-conv_000001] `) for continuous visibility.
- In single-persona mode (one persona in contract or using `--persona` flag), session switching is disabled.
- Supported commands:
  - `h/help`: Show available controls.
  - `+/faster` or `-/slower`: Adjust turn playback speed.
  - `p/pause`: Pause or resume conversation turns.
  - `q/stop`: Stop the simulation early.
  - `style <mode>`: Dynamically set the communication style for the **currently active persona**. Each persona maintains its own behavior mode independently. Modes: `default`, `aggressive`, `polite`, `concise`, `confused`, `anxious`. When no persona is active, applies globally as a fallback.
  - `l/list` (disabled in single-persona runs): List all active conversation sessions.
  - `s/switch <persona_id-conversation_id|conversation_id>` (disabled in single-persona runs): Explicitly switch to another active conversation session.
- Behavior changes apply to the active persona and persist across session switches. Each persona can have its own distinct behavior mode.
- The prompt remains stable while logs stream above it, with active persona/session updating when switched.
- Long-running commands show a live bottom status bar with progress.
- In realtime chat with interactive controls enabled (default), the prompt stays above a pinned bottom status bar.
- If `prompt_toolkit` is unavailable, realtime interactive mode fails fast with a clear setup message.
- Controls are ephemeral and end automatically when the run completes or is stopped.

### Realtime Session Control Example
```bash
# List active sessions and the current focus (*)
⚡> l
Active sessions: *P001-conv_000001, P002-conv_000002, P003-conv_000003

# Switch to another active conversation session
⚡> s P002-conv_000002
Conversation updated

# Set behavior for the currently active persona (P002)
⚡> [P002-conv_000002] style aggressive
Behavior updated for P002

```

---

## Target Configurations & Execution Environments

### Chatbot Endpoint Configurations
To call a real chatbot endpoint, set `target.enabled: true`, provide `target.endpoint`, and set the configured auth environment variable.

### Browser UI Configuration
To drive a chatbot through a browser UI instead, set `target.mode: browser` and provide CSS selectors for the input, submit button, and bot responses:

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
```

Browser mode uses Playwright. By default it uses `browser_type: chromium`, but you can set it to `browser_type: edge` to launch Microsoft Edge via the `msedge` channel. All chatbot turns are processed sequentially because browser sessions cannot process concurrent turns.

### Windows OneDrive Environment Setup
If `uv run` fails on Windows OneDrive paths with a hardlink error (such as `os error 396`), switch uv to copy mode:

```powershell
$env:UV_LINK_MODE='copy'
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat
```

For specific unified evaluation execution examples (including running specific personas), see the usage comments at the top of individual contract files like `contracts/examples/unified_evaluation_demo.yaml`.

---

## AWS Bedrock AgentCore Setup and Execution

### Step 1: Configure AWS Credentials
```powershell
aws configure
```
Sets up your AWS credentials (Access Key ID, Secret Access Key, default region) for accessing AWS Bedrock services. This creates a `~/.aws/credentials` file.

### Step 2: Verify AWS Identity
```powershell
aws sts get-caller-identity
```
Confirms that your AWS credentials are valid and displays your AWS account ID, user ARN, and assumed role information.

### Step 3: Configure Corporate SSL Certificate (if needed)
```powershell
$env:AWS_CA_BUNDLE="path\to\cert.pem"
```
In corporate environments with SSL inspection, this tells AWS SDK to trust your organization's CA certificate. Replace the path with your actual certificate location.

### Step 4: Install Package in Development Mode
```powershell
uv pip install -e .
```
Installs the `adaptive-synth-eval` package in editable mode, allowing you to make code changes without reinstalling.

### Step 5: Execute TFSA Evaluation Contracts

For full execution examples (including running in batch mode, real-time chat mode, or targeting specific personas), refer to the usage comments documented at the top of the specific TFSA contract files:
- [tfsa_aws_unified_evaluation_no_reasoning.yaml](../contracts/examples/tfsa_aws_unified_evaluation_no_reasoning.yaml)
- [tfsa_aws_unified_evaluation_reasoning.yaml](../contracts/examples/tfsa_aws_unified_evaluation_reasoning.yaml)

---

## Corporate Environment Setup

If you're working behind a corporate proxy or firewall, you may need additional configuration:

### SSL Certificate Configuration
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

### Proxy Configuration
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

> [!NOTE]
> If your username contains special characters (like backslashes in domain usernames), URL-encode them:
> ```powershell
> $username = [uri]::EscapeDataString("DOMAIN\\username")
> $password = [uri]::EscapeDataString("your-password")
> $env:HTTP_PROXY = "http://${username}:${password}@proxy.company.com:8080/"
> $env:HTTPS_PROXY = "http://${username}:${password}@proxy.company.com:8080/"
> ```
>  **For Git operations:**
>  ```bash
>  git config --global http.proxy "http://${username}:${password}@proxy.company.com:8080/"
>  git config --global https.proxy "http://${username}:${password}@proxy.company.com:8080/"
>  ```

### Persistent Configuration
Add the settings to your shell profile (`~/.bashrc`, `~/.zshrc`) on Linux/macOS, or environment properties on Windows.

### Troubleshooting Corporate Network Issues
- **SSL errors**: Verify the CA certificate path is correct and the file exists.
- **Connection timeouts**: Check proxy address and port with IT.
- **Authentication failures**: Ensure credentials are URL-encoded.
- **uv sync fails**: Set `UV_HTTP_TIMEOUT=300` for longer timeouts.
