# CLI Usage

Validate a contract:

```bash
uv run adaptive-synth-eval validate-contract contracts/examples/one_week_chat_history.yaml
```

Generate one week of dry-run ChatHistory:

```bash
uv run adaptive-synth-eval run --contract contracts/examples/one_week_chat_history.yaml --dry-run
```

Generate the 10,000-conversation dataset:

```bash
uv run adaptive-synth-eval run --contract contracts/examples/ten_k_conversations.yaml --dry-run
```

Summarize a run:

```bash
uv run adaptive-synth-eval summarize --run-id one_week_chat_history
```

Run a focused chatbot unit test:

```bash
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run
```

Output conversations in human-readable format (with Persona/Bot labels):

```bash
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --output-conversations
```

This generates a `conversations.txt` file in the output directory with each conversation formatted as:
- Conversation metadata (ID, session, persona, scenario, synthetic day)
- Alternating "Persona (Turn N):" and "Bot (Turn N):" messages
- Error indicators if any occurred

See [docs/example_conversations_output.txt](example_conversations_output.txt) for a sample output.

Stream Persona/Bot chat to the console in real time:

```bash
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat
```

Disable interactive runtime controls during realtime chat (controls are enabled by default with `--realtime-chat`):

```bash
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --realtime-chat --no-interactive-realtime-controls
```

How `--realtime-chat` works:
- It is opt-in and only runs when `persona_pool` contains exactly one persona.
- For single-persona contracts, each turn is printed live as alternating Human and Assistant panels.
- For multi-persona contracts, live output is skipped and a console notice is printed.
- It does not replace output artifacts; files like `chat_history.jsonl` and `conversations.txt` (when enabled) are still generated normally.

How `--interactive-realtime-controls` works:
- It is enabled by default when `--realtime-chat` is enabled.
- Use `--no-interactive-realtime-controls` to turn it off.
- During the run, type a command and press Enter to control playback.
- Supported commands: `h/help`, `s/status`, `+/faster`, `-/slower`, `p/pause`, `q/stop`, `style <mode>`.
- Behavior modes for `style`: `default`, `aggressive`, `polite`, `concise`, `confused`, `anxious`.
- Behavior changes apply to upcoming generated user turns, so you can steer conversation tone live.
- The `realtime>` prompt remains stable while logs stream above it (Copilot CLI-style input behavior).
- Controls are ephemeral and end automatically when the run completes or is stopped.

To call a real chatbot endpoint, set `target_chatbot.enabled: true`, provide `target_chatbot.endpoint`, and set the configured auth environment variable.

If `uv run` fails on Windows OneDrive paths with a hardlink error (such as `os error 396`), switch uv to copy mode:

```powershell
$env:UV_LINK_MODE='copy'
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --realtime-chat
```
