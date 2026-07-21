"""Typed request and response schemas for the metrics API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetricSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    evaluation_group: str
    label: str
    description: str
    detail: str
    eval_input_key: str
    warn_below: float
    fail_below: float
    invert_llm_score: bool
    prompt_template: str
    heuristic: dict[str, Any] | None
    content_fingerprint: str
    policy_fingerprint: str
    judge: dict[str, str | None] | None


class MetricCatalogResponse(BaseModel):
    metrics: list[MetricSpecResponse]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


BoundedText = Annotated[str, Field(max_length=65_536)]
MetricKey = Annotated[str, Field(min_length=1, max_length=128)]


class EvaluationInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: BoundedText
    chatbot_response: BoundedText
    reference_context: BoundedText | None = None
    reference_answer: BoundedText | None = None


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: EvaluationInputRequest
    metric_keys: list[MetricKey] | None = Field(default=None, max_length=10)


class MetricResultResponse(BaseModel):
    metric_key: str
    score: float
    percent: float
    status: Literal["pass", "warn", "fail"]
    quality: Literal["llm", "heuristic_fallback"]
    detail: str
    content_fingerprint: str
    policy_fingerprint: str
    judge_fingerprint: str
    reference_mode: Literal["reference_backed", "query_only", "not_applicable"]


class EvaluationResponse(BaseModel):
    results: list[MetricResultResponse]


class BatchEvaluationItemRequest(EvaluationRequest):
    id: str = Field(min_length=1, max_length=128)

    @field_validator("id")
    @classmethod
    def id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("id must not be blank")
        return value


class BatchEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BatchEvaluationItemRequest] = Field(min_length=1, max_length=100)


class BatchSuccessItem(BaseModel):
    id: str
    result: EvaluationResponse


class BatchErrorItem(BaseModel):
    id: str
    error: ErrorBody


class BatchEvaluationResponse(BaseModel):
    items: list[BatchSuccessItem | BatchErrorItem]
