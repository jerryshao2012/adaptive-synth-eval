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

- `${RAG_ENDPOINT}` - replaced with the value of the `RAG_ENDPOINT` environment variable
- `${RAG_ENDPOINT:-https://default.example.com}` - uses the env var if set, otherwise falls back to the default value

This is particularly useful for the `target_chatbot.endpoint` field to avoid hardcoding endpoints:

```yaml
target_chatbot:
  enabled: true
  endpoint: "${RAG_ENDPOINT:-https://api.example.com/v1/chat}"
  auth:
    type: bearer
    env_var: CHATBOT_API_TOKEN
```

When `RAG_ENDPOINT` is set in your environment, it will override the default. Otherwise, the fallback value is used.

## Examples

- `contracts/examples/one_week_chat_history.yaml`: A comprehensive 7-day simulation plan.
- `contracts/examples/chatbot_test_contract.yaml`: A focused contract for unit testing chatbot client functionality.
- `contracts/examples/ten_k_conversations.yaml`: A scale test contract for 10,000 conversations.
