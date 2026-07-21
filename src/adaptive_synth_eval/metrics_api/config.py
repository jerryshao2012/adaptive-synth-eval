"""Runtime configuration for the standalone metrics API."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


class ApiSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: str = Field(min_length=1)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    max_batch_size: int = Field(default=50, ge=1, le=100)

    @classmethod
    def from_env(cls) -> "ApiSettings":
        api_key = os.getenv("ASE_METRICS_API_KEY", "").strip()
        if not api_key:
            raise ValueError("ASE_METRICS_API_KEY must be configured and non-empty.")
        return cls(
            api_key=api_key,
            max_concurrency=os.getenv("ASE_METRICS_MAX_CONCURRENCY", "4"),
            max_batch_size=os.getenv("ASE_METRICS_MAX_BATCH_SIZE", "50"),
        )
