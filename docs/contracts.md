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

## Examples

- `contracts/examples/one_week_chat_history.yaml`: A comprehensive 7-day simulation plan.
- `contracts/examples/chatbot_test_contract.yaml`: A focused contract for unit testing chatbot client functionality.
- `contracts/examples/ten_k_conversations.yaml`: A scale test contract for 10,000 conversations.
