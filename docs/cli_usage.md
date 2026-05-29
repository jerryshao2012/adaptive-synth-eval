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

How `--interactive-realtime-controls` works:
- It is enabled by default when `--realtime-chat` is enabled.
- Use `--no-interactive-realtime-controls` to turn it off.
- During the run, type a command and press Enter to control playback.
- Supported commands:
  - `h/help`: Show available controls.
  - `s/status`: Show current playback speed, mode, active behavior, and active persona.
  - `+/faster` or `-/slower`: Adjust turn playback speed.
  - `p/pause`: Pause or resume conversation turns.
  - `q/stop`: Stop the simulation early.
  - `style <mode>`: Dynamically set the communication style of subsequent turns. Modes: `default`, `aggressive`, `polite`, `concise`, `confused`, `anxious`.
  - `personas`: List all persona IDs available in the simulation pool.
  - `persona <persona_id>` or `switch <persona_id>`: Dynamically switch the user simulator to a different persona mid-conversation.
- Behavior and persona changes apply to upcoming generated user turns, so you can steer conversation tone and identity live.
- The `⚡>` prompt remains stable while logs stream above it.
- Controls are ephemeral and end automatically when the run completes or is stopped.

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
uv run ase run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --realtime-chat
```
