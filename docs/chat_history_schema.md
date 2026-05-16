# ChatHistory Schema

Each row in `chat_history.jsonl` and `chat_history.csv` represents one turn.

Fields:

- `conversation_id`
- `session_id`
- `synthetic_day`
- `persona_id`
- `scenario_id`
- `turn_id`
- `user_message`
- `bot_response`
- `expected_retrieval_topics`
- `planned_failure_modes`
- `applied_failure_modes`
- `groundedness_score`
- `relevance_score`
- `safety_score`
- `clarification_score`
- `failure_mode`
- `latency_ms`
- `error`
- `synthetic_flag`

Optional fields:

- `retrieved_policy_ids`
- `response_raw`
- `generation_metadata`

Tool-call fields are intentionally not required.
