import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from adaptive_synth_eval.clients.llm import LLMClient
from adaptive_synth_eval.metrics_api.app import create_app
from adaptive_synth_eval.metrics_api.config import ApiSettings
from adaptive_synth_eval.metrics_api.errors import EvaluationServiceUnavailable
from adaptive_synth_eval.monitoring.evaluator import (
    JudgeConfigurationError,
    MetricEvaluator,
)
from adaptive_synth_eval.monitoring.metric_definitions import load_metrics_config

API_KEY = "test-api-key"


def make_evaluator() -> MetricEvaluator:
    return MetricEvaluator(
        metrics_config=load_metrics_config(),
        default_llm=LLMClient(enabled=False),
        dry_run=True,
    )


def make_app(evaluator=None):
    return create_app(
        settings=ApiSettings(
            api_key=API_KEY,
            max_concurrency=2,
            max_batch_size=3,
        ),
        evaluator=evaluator or make_evaluator(),
    )


class ApiJudge:
    model_provider = "openai"
    config = {"model": "api-judge"}

    def complete(self, prompt, **kwargs):
        keys = json.loads(
            kwargs["system_prompt"].split("exactly these keys: ", 1)[1].split(".", 1)[0]
        )
        return SimpleNamespace(
            content=json.dumps({key: 0.8 for key in keys}),
            error=None,
        )


def make_live_evaluator():
    return MetricEvaluator(
        metrics_config=load_metrics_config(),
        default_llm=ApiJudge(),
    )


def test_health_is_public_and_contains_only_liveness_status():
    with TestClient(make_app()) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_key_middleware_protects_defined_and_unmatched_paths():
    with TestClient(make_app()) as client:
        missing = client.get("/v1/metrics")
        wrong = client.get("/v1/metrics", headers={"X-API-Key": "wrong"})
        unmatched = client.get("/not-a-route")
        authenticated = client.get(
            "/not-a-route",
            headers={"X-API-Key": API_KEY},
        )

    expected = {
        "error": {
            "code": "invalid_api_key",
            "message": "A valid API key is required.",
        }
    }
    assert missing.status_code == 401
    assert missing.json() == expected
    assert wrong.status_code == 401
    assert wrong.json() == expected
    assert unmatched.status_code == 401
    assert unmatched.json() == expected
    assert authenticated.status_code == 404


def test_metric_catalog_exposes_ten_sanitized_parsed_specs():
    headers = {"X-API-Key": API_KEY}
    with TestClient(make_app()) as client:
        response = client.get("/v1/metrics", headers=headers)
        detail = client.get("/v1/metrics/relevance", headers=headers)

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert len(metrics) == 10
    assert {metric["key"] for metric in metrics} == set(
        load_metrics_config().metrics
    )
    assert detail.status_code == 200
    relevance = detail.json()
    assert relevance["key"] == "relevance"
    assert relevance["prompt_template"]
    assert len(relevance["content_fingerprint"]) == 16
    assert len(relevance["policy_fingerprint"]) == 16
    assert "api_key_env" not in response.text


def test_unknown_catalog_metric_uses_stable_404_error():
    with TestClient(make_app()) as client:
        response = client.get(
            "/v1/metrics/missing",
            headers={"X-API-Key": API_KEY},
        )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "metric_not_found",
            "message": "Metric 'missing' was not found.",
        }
    }


def test_single_evaluation_returns_auditable_selected_results():
    with TestClient(make_app(make_live_evaluator())) as client:
        response = client.post(
            "/v1/evaluations",
            headers={"X-API-Key": API_KEY},
            json={
                "input": {
                    "user_message": "Question",
                    "chatbot_response": "Answer",
                },
                "metric_keys": ["relevance", "toxicity"],
            },
        )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [result["metric_key"] for result in results] == [
        "relevance",
        "toxicity",
    ]
    assert results[0]["score"] == 0.8
    assert results[0]["quality"] == "llm"
    assert results[0]["reference_mode"] == "not_applicable"
    assert results[1]["score"] == 0.2
    assert len(results[0]["judge_fingerprint"]) == 16


def test_single_evaluation_rejects_unknown_metric_with_stable_422():
    with TestClient(make_app(make_live_evaluator())) as client:
        response = client.post(
            "/v1/evaluations",
            headers={"X-API-Key": API_KEY},
            json={
                "input": {
                    "user_message": "Question",
                    "chatbot_response": "Answer",
                },
                "metric_keys": ["missing"],
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "unknown_metric",
            "message": "One or more requested metrics do not exist.",
            "details": {"unknown_metric_keys": ["missing"]},
        }
    }


def test_batch_preserves_order_and_isolates_semantic_item_errors():
    with TestClient(make_app(make_live_evaluator())) as client:
        response = client.post(
            "/v1/evaluations/batch",
            headers={"X-API-Key": API_KEY},
            json={
                "items": [
                    {
                        "id": "ok",
                        "input": {
                            "user_message": "Question",
                            "chatbot_response": "Answer",
                        },
                        "metric_keys": ["relevance"],
                    },
                    {
                        "id": "bad",
                        "input": {
                            "user_message": "Question",
                            "chatbot_response": "Answer",
                        },
                        "metric_keys": ["missing"],
                    },
                ]
            },
        )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == ["ok", "bad"]
    assert items[0]["result"]["results"][0]["metric_key"] == "relevance"
    assert "error" not in items[0]
    assert items[1]["error"]["code"] == "unknown_metric"
    assert "result" not in items[1]


def test_batch_rejects_duplicate_ids_and_configured_size_limit():
    item = {
        "id": "same",
        "input": {"user_message": "Question", "chatbot_response": "Answer"},
    }
    headers = {"X-API-Key": API_KEY}
    with TestClient(make_app()) as client:
        duplicate = client.post(
            "/v1/evaluations/batch",
            headers=headers,
            json={"items": [item, item]},
        )
        oversized = client.post(
            "/v1/evaluations/batch",
            headers=headers,
            json={
                "items": [
                    {**item, "id": f"item-{index}"}
                    for index in range(4)
                ]
            },
        )

    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "duplicate_batch_id"
    assert oversized.status_code == 422
    assert oversized.json()["error"]["code"] == "batch_too_large"


def test_request_validation_uses_stable_error_envelope():
    with TestClient(make_app()) as client:
        response = client.post(
            "/v1/evaluations",
            headers={"X-API-Key": API_KEY},
            json={"input": {"user_message": "Question"}},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "chatbot_response" in json.dumps(response.json()["error"]["details"])


def test_single_unexpected_failure_is_redacted_from_response_and_logs(caplog):
    class FailingEvaluator:
        metrics_config = load_metrics_config()

        def evaluate(self, *_args, **_kwargs):
            raise RuntimeError("sensitive provider failure")

    caplog.set_level(logging.ERROR, logger="adaptive_synth_eval.metrics_api.app")
    with TestClient(
        make_app(FailingEvaluator()),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/v1/evaluations",
            headers={"X-API-Key": API_KEY},
            json={
                "input": {
                    "user_message": "Question",
                    "chatbot_response": "Answer",
                }
            },
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "evaluation_failed",
            "message": "The evaluation could not be completed.",
        }
    }
    assert "sensitive" not in response.text
    assert "sensitive provider failure" not in caplog.text
    assert "exception_type=RuntimeError" in caplog.text


def test_openapi_and_documentation_routes_are_unauthenticated():
    headers = {"X-API-Key": API_KEY}
    with TestClient(make_app()) as client:
        for path in ("/openapi.json", "/docs", "/redoc"):
            assert client.get(path).status_code == 200
        schema_response = client.get("/openapi.json", headers=headers)
        docs_response = client.get("/docs", headers=headers)
        redoc_response = client.get("/redoc", headers=headers)

    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert schema["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    assert schema["security"] == [{"ApiKeyAuth": []}]
    assert API_KEY not in schema_response.text
    assert docs_response.status_code == 200
    assert redoc_response.status_code == 200
    assert "/openapi.json" not in docs_response.text
    assert "/openapi.json" not in redoc_response.text
    assert '"openapi"' in docs_response.text
    assert '"openapi"' in redoc_response.text


def test_unavailable_evaluation_dependency_has_stable_single_and_batch_errors():
    class UnavailableEvaluator:
        metrics_config = load_metrics_config()

        def evaluate(self, *_args, **_kwargs):
            raise EvaluationServiceUnavailable()

    headers = {"X-API-Key": API_KEY}
    payload = {
        "input": {
            "user_message": "Question",
            "chatbot_response": "Answer",
        },
        "metric_keys": ["relevance"],
    }
    with TestClient(make_app(UnavailableEvaluator())) as client:
        single = client.post("/v1/evaluations", headers=headers, json=payload)
        batch = client.post(
            "/v1/evaluations/batch",
            headers=headers,
            json={"items": [{"id": "unavailable", **payload}]},
        )

    expected = {
        "code": "service_unavailable",
        "message": "The evaluation service is temporarily unavailable.",
    }
    assert single.status_code == 503
    assert single.json() == {"error": expected}
    assert batch.status_code == 200
    assert batch.json()["items"] == [
        {"id": "unavailable", "error": expected}
    ]


def test_api_settings_require_key_and_validate_resource_bounds(monkeypatch):
    monkeypatch.delenv("ASE_METRICS_API_KEY", raising=False)
    monkeypatch.setenv("ASE_METRICS_MAX_CONCURRENCY", "0")
    monkeypatch.setenv("ASE_METRICS_MAX_BATCH_SIZE", "101")

    with pytest.raises(ValueError, match="ASE_METRICS_API_KEY"):
        ApiSettings.from_env()

    monkeypatch.setenv("ASE_METRICS_API_KEY", "configured-key")
    with pytest.raises(ValueError):
        ApiSettings.from_env()


def test_application_startup_fails_without_judge_provider(monkeypatch):
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OLLAMA_BASE_URL",
        "OLLAMA_API_BASE",
        "AWS_BEARER_TOKEN_BEDROCK",
    ):
        monkeypatch.delenv(name, raising=False)
    app = create_app(
        settings=ApiSettings(api_key=API_KEY),
    )

    with pytest.raises(JudgeConfigurationError, match="No LLM provider"):
        with TestClient(app):
            pass


def test_batch_isolates_unexpected_item_failure_without_logging_secrets(caplog):
    class ConditionalEvaluator:
        def __init__(self):
            self.delegate = make_live_evaluator()
            self.metrics_config = self.delegate.metrics_config

        def evaluate(self, inputs, **kwargs):
            if inputs.user_message == "explode":
                raise RuntimeError("provider secret")
            return self.delegate.evaluate(inputs, **kwargs)

    caplog.set_level(logging.ERROR, logger="adaptive_synth_eval.metrics_api.app")
    with TestClient(make_app(ConditionalEvaluator())) as client:
        response = client.post(
            "/v1/evaluations/batch",
            headers={"X-API-Key": API_KEY},
            json={
                "items": [
                    {
                        "id": "ok",
                        "input": {
                            "user_message": "Question",
                            "chatbot_response": "Answer",
                        },
                        "metric_keys": ["relevance"],
                    },
                    {
                        "id": "failed",
                        "input": {
                            "user_message": "explode",
                            "chatbot_response": "Answer",
                        },
                        "metric_keys": ["relevance"],
                    },
                ]
            },
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["result"]
    assert response.json()["items"][1]["error"] == {
        "code": "evaluation_failed",
        "message": "The evaluation could not be completed.",
    }
    assert "provider secret" not in response.text
    assert "provider secret" not in caplog.text
    assert "exception_type=RuntimeError" in caplog.text


def test_process_semaphore_bounds_single_and_batch_requests_together():
    class TrackingEvaluator:
        def __init__(self):
            self.delegate = make_live_evaluator()
            self.metrics_config = self.delegate.metrics_config
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def evaluate(self, inputs, **kwargs):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.05)
                return self.delegate.evaluate(inputs, **kwargs)
            finally:
                with self.lock:
                    self.active -= 1

    evaluator = TrackingEvaluator()
    headers = {"X-API-Key": API_KEY}
    single = {
        "input": {"user_message": "Question", "chatbot_response": "Answer"},
        "metric_keys": ["relevance"],
    }
    batch = {
        "items": [
            {
                "id": f"item-{index}",
                **single,
            }
            for index in range(3)
        ]
    }
    with TestClient(make_app(evaluator)) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            single_future = pool.submit(
                client.post,
                "/v1/evaluations",
                headers=headers,
                json=single,
            )
            batch_future = pool.submit(
                client.post,
                "/v1/evaluations/batch",
                headers=headers,
                json=batch,
            )
            responses = [single_future.result(), batch_future.result()]

    assert [response.status_code for response in responses] == [200, 200]
    assert evaluator.max_active == 2
