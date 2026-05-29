# CLI Usage

For convenience, you can use the shorthand command `ase` instead of the full `adaptive-synth-eval` command.

### Running with uv
Prefix commands with `uv run ase`:
```bash
uv run ase validate-contract contracts/examples/one_week_chat_history.yaml
```

### Running Globally (No `uv run` prefix)
You can install the tool globally so that `ase` is available in your PATH from any directory:
```bash
uv tool install --editable .
```
Then, you can run commands directly:
```bash
ase validate-contract contracts/examples/one_week_chat_history.yaml
```

---

Validate a contract:

```bash
uv run ase validate-contract contracts/examples/one_week_chat_history.yaml
```

Generate one week of dry-run ChatHistory:

```bash
uv run ase run --contract contracts/examples/one_week_chat_history.yaml --dry-run
```

Generate the 10,000-conversation dataset:

```bash
uv run ase run --contract contracts/examples/ten_k_conversations.yaml --dry-run
```

Summarize a run:

```bash
uv run ase summarize --run-id one_week_chat_history
```

Run a focused chatbot unit test:

```bash
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
```

Output conversations in human-readable format (with Persona/Bot labels):

```bash
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --output-conversations
```

This generates a `conversations.txt` file in the output directory with each conversation formatted as:
- Conversation metadata (ID, session, persona, scenario, synthetic day)
- Alternating "Persona (Turn N):" and "Bot (Turn N):" messages
- Error indicators if any occurred

See [docs/example_conversations_output.txt](example_conversations_output.txt) for a sample output.

Stream Persona/Bot chat to the console in real time:

```bash
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat
```

Disable interactive runtime controls during realtime chat (controls are enabled by default with `--realtime-chat`):

```bash
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat --no-interactive-realtime-controls
```

How `--realtime-chat` works:
- It is opt-in and streams conversations directly in the console as alternating Human and Assistant panels.
- It supports both single-persona and multi-persona simulation pools, processing conversations in a clean sequential order.
- It does not replace output artifacts; files like `chat_history.jsonl` and `conversations.txt` (when enabled) are still generated normally.

How `--persona <id>` works:
- Limit the terminal simulation session to a single specific persona ID.
- Useful for running multiple terminals in parallel targeting different personas.
- Automatically disables the realtime commands `personas`, `persona <id>`, and `switch <id>`.

How `--interactive-realtime-controls` works:
- It is enabled by default when `--realtime-chat` is enabled.
- Use `--no-interactive-realtime-controls` to turn it off.
- During the run, type a command and press Enter to control playback.
- Offers interactive auto-hinting / auto-completion of commands and arguments as you type.
- In multi-persona mode, the prompt displays the current active persona ID (e.g., `⚡> [P001] `) for continuous visibility.
- In single-persona mode (one persona in contract or using `--persona` flag), the prompt remains as `⚡> ` without the persona ID since switching is disabled.
- Supported commands:
  - `h/help`: Show available controls.
  - `s/status`: Show current playback speed, mode, active behavior, and active persona.
  - `+/faster` or `-/slower`: Adjust turn playback speed.
  - `p/pause`: Pause or resume conversation turns.
  - `q/stop`: Stop the simulation early.
  - `style <mode>`: Dynamically set the communication style for the **currently active persona**. Each persona maintains its own behavior mode independently. Modes: `default`, `aggressive`, `polite`, `concise`, `confused`, `anxious`. When no persona is active, applies globally as a fallback.
  - `personas` (disabled in single-persona runs): List all persona IDs available in the simulation pool.
  - `persona <persona_id>` or `switch <persona_id>` (disabled in single-persona runs): Dynamically switch the user simulator to a different persona mid-conversation.
- Behavior changes apply to the active persona and persist across persona switches. Each persona can have its own distinct behavior mode.
- The prompt remains stable while logs stream above it, with the persona ID updating dynamically when switched.
- Controls are ephemeral and end automatically when the run completes or is stopped.

**Per-Persona Behavior Example:**
```bash
# Set P001 to aggressive mode
⚡> [P001] style aggressive
Behavior updated for P001

# Switch to P002 and set different behavior
⚡> [P001] persona P002
Persona updated
⚡> [P002] style polite
Behavior updated for P002

# Switch back to P001 - retains 'aggressive' behavior
⚡> [P002] persona P001
Persona updated
⚡> [P001] status
Status: delay=0.80s, mode=running, behavior=aggressive, persona=P001
```

To call a real chatbot endpoint, set `target_chatbot.enabled: true`, provide `target_chatbot.endpoint`, and set the configured auth environment variable.

To drive a chatbot through a browser UI instead, set `target_chatbot.mode: browser` and provide CSS selectors for the input, submit button, and bot responses:

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
```

Browser mode uses Playwright. By default it uses `browser_type: chromium`, but you can set it to `browser_type: edge` to launch Microsoft Edge via the `msedge` channel. All chatbot turns are processed sequentially because browser sessions cannot process concurrent turns.

If `uv run` fails on Windows OneDrive paths with a hardlink error (such as `os error 396`), switch uv to copy mode:

```powershell
$env:UV_LINK_MODE='copy'
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat

uv run ase run --contract contracts/examples/multi_persona_demo.yaml --realtime-chat
uv run ase run --contract contracts/examples/multi_persona_demo.yaml --realtime-chat --persona DEMO_P1
uv run ase run --contract contracts/examples/multi_persona_demo.yaml --realtime-chat --persona DEMO_P2
```
