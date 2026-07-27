"""FastAPI application factory for standalone metric evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from adaptive_synth_eval.config.env import load_project_env
from adaptive_synth_eval.metrics_api.config import ApiSettings
from adaptive_synth_eval.metrics_api.errors import EvaluationServiceUnavailable
from adaptive_synth_eval.metrics_api.schemas import (
    BatchErrorItem,
    BatchEvaluationRequest,
    BatchEvaluationResponse,
    BatchSuccessItem,
    ErrorBody,
    EvaluationRequest,
    EvaluationResponse,
    MetricCatalogResponse,
    MetricResultResponse,
    MetricSpecResponse,
)
from adaptive_synth_eval.monitoring.evaluator import (
    EvaluationInput,
    MetricEvaluator,
    MetricSelectionError,
)
from adaptive_synth_eval.monitoring.fingerprint import compute_policy_fingerprint
from adaptive_synth_eval.monitoring.metrics._base import MetricSpec

logger = logging.getLogger(__name__)


def _log_unexpected_failure(context: str, exc: Exception) -> None:
    """Record a traceable failure without provider messages or tracebacks."""
    logger.error(
        "%s correlation_id=%s exception_type=%s",
        context,
        uuid4().hex,
        type(exc).__name__,
    )


def _embedded_openapi(app: FastAPI) -> str:
    """Serialize the schema safely for an inline JavaScript object literal."""
    return json.dumps(app.openapi(), ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )


def _serialize_metric(metric: MetricSpec) -> MetricSpecResponse:
    payload = metric.to_public_dict()
    payload["policy_fingerprint"] = compute_policy_fingerprint(
        metric_key=metric.key,
        warn_below=metric.warn_below,
        fail_below=metric.fail_below,
    )
    return MetricSpecResponse.model_validate(payload)


def _serialize_evaluation(result) -> EvaluationResponse:
    return EvaluationResponse(
        results=[
            MetricResultResponse.model_validate(
                {
                    "metric_key": metric.metric_key,
                    "score": metric.score,
                    "percent": metric.percent,
                    "status": metric.status,
                    "quality": metric.quality,
                    "detail": metric.detail,
                    "content_fingerprint": metric.content_fingerprint,
                    "policy_fingerprint": metric.policy_fingerprint,
                    "judge_fingerprint": metric.judge_fingerprint,
                    "reference_mode": metric.reference_mode,
                }
            )
            for metric in result.results
        ]
    )


def create_app(
    *,
    settings: ApiSettings | None = None,
    evaluator: MetricEvaluator | None = None,
) -> FastAPI:
    if settings is None:
        load_project_env(anchor=Path.cwd())
    resolved_settings = settings or ApiSettings.from_env()
    validate_runtime_evaluator = evaluator is None
    resolved_evaluator = evaluator or MetricEvaluator()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if validate_runtime_evaluator:
            resolved_evaluator.validate_startup()
        app.state.settings = resolved_settings
        app.state.evaluator = resolved_evaluator
        app.state.evaluation_semaphore = asyncio.Semaphore(
            resolved_settings.max_concurrency
        )
        yield

    app = FastAPI(
        title="AI Evals Metrics API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    def protected_openapi_schema():
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title,
                version=app.version,
                routes=app.routes,
            )
            schema.setdefault("components", {}).setdefault("securitySchemes", {})[
                "ApiKeyAuth"
            ] = {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
            }
            schema["security"] = [{"ApiKeyAuth": []}]
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = protected_openapi_schema

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "type": error.get("type", "validation_error"),
                "loc": list(error.get("loc", ())),
                "msg": error.get("msg", "Invalid value"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request payload is invalid.",
                    "details": details,
                }
            },
        )

    @app.middleware("http")
    async def require_api_key(request: Request, call_next):
        if request.url.path in ("/healthz", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)
        supplied = request.headers.get("X-API-Key", "")
        expected = resolved_settings.api_key if resolved_settings is not None else ""
        if not expected or not secrets.compare_digest(supplied, expected):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "invalid_api_key",
                        "message": "A valid API key is required.",
                    }
                },
            )
        return await call_next(request)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi_json():
        return JSONResponse(content=app.openapi())

    @app.get("/docs", include_in_schema=False)
    async def swagger_docs() -> HTMLResponse:
        schema = _embedded_openapi(app)
        return HTMLResponse(
            "<!DOCTYPE html><html><head>"
            f"<title>{app.title} - Swagger UI</title>"
            '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">'
            '</head><body><div id="swagger-ui"></div>'
            '<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>'
            f"<script>SwaggerUIBundle({{spec:{schema},dom_id:'#swagger-ui',deepLinking:true}});</script>"
            "</body></html>"
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_docs() -> HTMLResponse:
        schema = _embedded_openapi(app)
        return HTMLResponse(
            "<!DOCTYPE html><html><head>"
            f"<title>{app.title} - ReDoc</title>"
            '</head><body><div id="redoc-container"></div>'
            '<script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>'
            f"<script>Redoc.init({schema},{{}},document.getElementById('redoc-container'));</script>"
            "</body></html>"
        )

    @app.get("/v1/metrics", response_model=MetricCatalogResponse)
    async def list_metrics() -> MetricCatalogResponse:
        assert resolved_evaluator is not None
        return MetricCatalogResponse(
            metrics=[
                _serialize_metric(metric)
                for metric in resolved_evaluator.metrics_config.metrics.values()
            ]
        )

    @app.get("/v1/metrics/{metric_key}", response_model=MetricSpecResponse)
    async def get_metric(metric_key: str):
        assert resolved_evaluator is not None
        metric = resolved_evaluator.metrics_config.metrics.get(metric_key)
        if metric is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "metric_not_found",
                        "message": f"Metric '{metric_key}' was not found.",
                    }
                },
            )
        return _serialize_metric(metric)

    @app.post("/v1/evaluations", response_model=EvaluationResponse)
    async def evaluate_metrics(request: EvaluationRequest):
        assert resolved_evaluator is not None
        evaluation_input = EvaluationInput(
            user_message=request.input.user_message,
            chatbot_response=request.input.chatbot_response,
            reference_context=request.input.reference_context,
            reference_answer=request.input.reference_answer,
        )
        try:
            async with app.state.evaluation_semaphore:
                result = await run_in_threadpool(
                    partial(
                        resolved_evaluator.evaluate,
                        evaluation_input,
                        metric_keys=request.metric_keys,
                    )
                )
            response = _serialize_evaluation(result)
        except MetricSelectionError as exc:
            error = {"code": exc.code, "message": str(exc)}
            if exc.details is not None:
                error["details"] = exc.details
            return JSONResponse(status_code=422, content={"error": error})
        except EvaluationServiceUnavailable:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "service_unavailable",
                        "message": (
                            "The evaluation service is temporarily unavailable."
                        ),
                    }
                },
            )
        except Exception as exc:
            _log_unexpected_failure(
                "Unexpected standalone metric evaluation failure",
                exc,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "evaluation_failed",
                        "message": "The evaluation could not be completed.",
                    }
                },
            )
        return response

    async def evaluate_batch_item(item):
        evaluation_input = EvaluationInput(
            user_message=item.input.user_message,
            chatbot_response=item.input.chatbot_response,
            reference_context=item.input.reference_context,
            reference_answer=item.input.reference_answer,
        )
        try:
            assert resolved_evaluator is not None
            async with app.state.evaluation_semaphore:
                result = await run_in_threadpool(
                    partial(
                        resolved_evaluator.evaluate,
                        evaluation_input,
                        metric_keys=item.metric_keys,
                    )
                )
            return BatchSuccessItem(
                id=item.id,
                result=_serialize_evaluation(result),
            )
        except MetricSelectionError as exc:
            return BatchErrorItem(
                id=item.id,
                error=ErrorBody(
                    code=exc.code,
                    message=str(exc),
                    details=exc.details,
                ),
            )
        except EvaluationServiceUnavailable:
            return BatchErrorItem(
                id=item.id,
                error=ErrorBody(
                    code="service_unavailable",
                    message="The evaluation service is temporarily unavailable.",
                ),
            )
        except Exception as exc:
            _log_unexpected_failure(
                "Unexpected standalone metric batch item failure",
                exc,
            )
            return BatchErrorItem(
                id=item.id,
                error=ErrorBody(
                    code="evaluation_failed",
                    message="The evaluation could not be completed.",
                ),
            )

    @app.post(
        "/v1/evaluations/batch",
        response_model=BatchEvaluationResponse,
        response_model_exclude_none=True,
    )
    async def evaluate_batch(request: BatchEvaluationRequest):
        assert resolved_settings is not None
        if len(request.items) > resolved_settings.max_batch_size:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "batch_too_large",
                        "message": (
                            "Batch contains more items than the configured maximum."
                        ),
                        "details": {
                            "max_batch_size": resolved_settings.max_batch_size,
                        },
                    }
                },
            )
        ids = [item.id for item in request.items]
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        if duplicates:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "duplicate_batch_id",
                        "message": "Batch item IDs must be unique.",
                        "details": {"duplicate_ids": duplicates},
                    }
                },
            )
        items = await asyncio.gather(
            *(evaluate_batch_item(item) for item in request.items)
        )
        return BatchEvaluationResponse(items=list(items))

    return app
