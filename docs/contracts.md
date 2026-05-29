# Simulation Contracts

Contracts are JSON or YAML and are the source of truth for simulation behavior.

Required sections:

- `simulation_suite`
- `target_chatbot`
- `time_window`
- `persona_pool`
- `scenario_catalog`
- `traffic_orchestration`
- `output`

Tool-call expectations are not active scope. If a legacy contract includes `tool_expectations`, validation warns and ignores the field.

Conversation turn ranges must be within 3-8 turns.

## Environment Variable Substitution

Contract files support environment variable substitution using `${VAR_NAME}` syntax:

- `${CHATBOT_ENDPOINT}` - replaced with the value of the `CHATBOT_ENDPOINT` environment variable
- `${CHATBOT_ENDPOINT:-https://default.example.com}` - uses the env var if set, otherwise falls back to the default value

This is particularly useful for the `target_chatbot.endpoint` field to avoid hardcoding endpoints:

```yaml
target_chatbot:
  enabled: true
  endpoint: "${CHATBOT_ENDPOINT:-https://api.example.com/v1/chat}"
  auth:
    type: bearer
    env_var: CHATBOT_API_TOKEN
```

When `CHATBOT_ENDPOINT` is set in your environment, it will override the default. Otherwise, the fallback value is used.

## Browser Chatbot Mode

The chatbot can also be driven through a generic browser UI instead of an HTTP API. This is useful when the target chatbot only exposes a web chat surface.

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
    ready_selector: "textarea"
    response_timeout_seconds: 60
    headless: false
```

Browser mode uses the following fields:

- `browser_type`: browser engine to launch. Options: `chromium` (default) or `edge` (which launches Microsoft Edge using Playwright's `msedge` channel).
- `input_selector`: element that receives the user message.
- `submit_selector`: element clicked to send the message.
- `response_selector`: bot message elements; the newest matching element is captured.
- `ready_selector`: optional element to wait for after page load. Defaults to `input_selector`.

Browser mode runs chatbot calls sequentially, even if `traffic_orchestration.max_concurrency` is higher, because a single browser chat page cannot safely process concurrent turns.

## Examples

- `contracts/examples/one_week_chat_history.yaml`: A comprehensive 7-day simulation plan.
- `contracts/examples/chatbot_test_contract.yaml`: A focused contract for unit testing chatbot client functionality.
- `contracts/examples/browser_chatbot_test.yaml`: A focused contract for testing browser-driven chatbot integration.
- `contracts/examples/ten_k_conversations.yaml`: A scale test contract for 10,000 conversations.
- `contracts/examples/multi_persona_demo.yaml`: A multi-persona contract demonstrating real-time chat and isolated persona runs.
