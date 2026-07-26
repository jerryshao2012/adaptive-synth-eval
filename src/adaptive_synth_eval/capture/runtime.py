"""Run-scoped capture construction controlled by explicit environment flags."""

from __future__ import annotations

import os
from pathlib import Path

from adaptive_synth_eval.capture.sinks import CaptureCoordinator


def capture_coordinator_from_env(run_dir: Path) -> CaptureCoordinator | None:
    """Create a coordinator only when optional capture is explicitly enabled."""
    if os.getenv("ASE_CAPTURE_ENABLED", "").strip().lower() != "true":
        return None
    raw_limit = os.getenv("ASE_CAPTURE_MAX_RECORDS_PER_PRODUCER", "1000")
    try:
        max_records = int(raw_limit)
    except ValueError as exc:
        raise ValueError(
            "ASE_CAPTURE_MAX_RECORDS_PER_PRODUCER must be a positive integer"
        ) from exc
    if max_records <= 0:
        raise ValueError(
            "ASE_CAPTURE_MAX_RECORDS_PER_PRODUCER must be a positive integer"
        )
    return CaptureCoordinator(
        run_dir,
        max_records_per_producer=max_records,
    )
