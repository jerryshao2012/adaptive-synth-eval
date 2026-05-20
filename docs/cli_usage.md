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

Output conversations in human-readable format (with Human/Bot labels):

```bash
uv run adaptive-synth-eval run --contract contracts/examples/chatbot_test_contract.yaml --dry-run --output-conversations
```

This generates a `conversations.txt` file in the output directory with each conversation formatted as:
- Conversation metadata (ID, session, persona, scenario, synthetic day)
- Alternating "Human (Turn N):" and "Bot (Turn N):" messages
- Error indicators if any occurred

See [docs/example_conversations_output.txt](example_conversations_output.txt) for a sample output.

To call a real chatbot endpoint, set `target_chatbot.enabled: true`, provide `target_chatbot.endpoint`, and set the configured auth environment variable.
