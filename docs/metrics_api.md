# Metrics API

The standalone metrics API is a Python FastAPI service for discovering ASE's ten packaged metric specifications and evaluating independent chatbot payloads. It does not depend on `ai-eval-dashboard`, run directories, or monitoring artifacts.

## Configure and launch

Set a non-empty API key and configure one supported judge provider using the variables in [Environment setup](environment_setup.md). The service uses the same provider auto-detection order as monitoring: Azure OpenAI, Anthropic, OpenAI, Ollama, then Bedrock.

```bash
export ASE_METRICS_API_KEY="replace-with-a-secret"
export ASE_METRICS_MAX_CONCURRENCY=4
export ASE_METRICS_MAX_BATCH_SIZE=50

uv run ase metrics serve --host 127.0.0.1 --port 8000 --workers 1
```

`ASE_METRICS_MAX_CONCURRENCY` must be 1-32 and applies to all single and batch evaluations within one worker. `ASE_METRICS_MAX_BATCH_SIZE` must be 1-100. Total possible judge concurrency is the configured concurrency multiplied by `--workers`.

Startup fails when the service API key, provider credentials, provider endpoint/model settings, or a metric-specific judge route is invalid. Runtime judge failures use explicit `heuristic_fallback` results only for the affected judge batch.

## Authentication and discovery

Every path except `/healthz` requires `X-API-Key`:

```bash
curl http://127.0.0.1:8000/healthz

curl -H "X-API-Key: $ASE_METRICS_API_KEY" \
  http://127.0.0.1:8000/v1/metrics

curl -H "X-API-Key: $ASE_METRICS_API_KEY" \
  http://127.0.0.1:8000/v1/metrics/groundedness
```

Authenticated OpenAPI and documentation routes are available at `/openapi.json`, `/docs`, and `/redoc`. Catalog responses contain parsed prompts, thresholds, heuristics, and fingerprints but never credential-variable selectors or secret values.

## Evaluate one tuple

Omit `metric_keys` to evaluate all ten metrics in catalog order. A provided list must be non-empty, unique, and contain only known keys; result order follows that list.

```bash
curl -X POST http://127.0.0.1:8000/v1/evaluations \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ASE_METRICS_API_KEY" \
  -d '{
    "input": {
      "user_message": "What does the leave policy require?",
      "chatbot_response": "Manager approval is required.",
      "reference_context": "Policy section 4 requires manager approval.",
      "reference_answer": "Manager approval is required."
    },
    "metric_keys": ["groundedness", "completeness", "relevance"]
  }'
```

Each metric result includes a normalized score, percentage, pass/warn/fail status, `llm` or `heuristic_fallback` quality, content/policy/judge fingerprints, and reference mode.

## Evaluate a batch

Batch items have unique IDs, independent payloads, and independent optional metric selections. Structurally valid batches return HTTP 200 in input order; semantic failures are isolated as `{id, error}` items while successful items use `{id, result}`.

```bash
curl -X POST http://127.0.0.1:8000/v1/evaluations/batch \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ASE_METRICS_API_KEY" \
  -d '{
    "items": [
      {
        "id": "case-1",
        "input": {
          "user_message": "Summarize the policy.",
          "chatbot_response": "The policy requires approval."
        },
        "metric_keys": ["relevance", "style"]
      }
    ]
  }'
```

The two required input strings and both optional reference strings are limited to 65,536 characters. Batch IDs are nonblank and at most 128 characters.
