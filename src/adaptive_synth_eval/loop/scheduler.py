from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from adaptive_synth_eval.loop.profiles import LoopProfile, LoopProfileError


def cadence_to_interval_seconds(cadence: str) -> float:
    text = cadence.strip()
    lower = text.lower()
    if lower == "hourly":
        return 3600.0
    if lower == "daily":
        return 86400.0

    minutes_match = re.fullmatch(r"every\s+(\d+)\s+minutes?", lower)
    if minutes_match:
        return float(int(minutes_match.group(1)) * 60)

    hours_match = re.fullmatch(r"every\s+(\d+)\s+hours?", lower)
    if hours_match:
        return float(int(hours_match.group(1)) * 3600)

    if re.fullmatch(r"\*/\d+\s+\*\s+\*\s+\*\s+\*", lower):
        interval_minutes = int(lower.split()[0].split("/")[1])
        return float(interval_minutes * 60)

    if re.fullmatch(r"0\s+\*/\d+\s+\*\s+\*\s+\*", lower):
        interval_hours = int(lower.split()[1].split("/")[1])
        return float(interval_hours * 3600)

    if lower == "0 * * * *":
        return 3600.0

    if re.fullmatch(r"0\s+\d+\s+\*\s+\*\s+.*", lower):
        return 86400.0

    raise LoopProfileError(f"Unsupported loop cadence format: {cadence}")


@dataclass
class LoopScheduler:
    sleep_fn: Callable[[float], None] = time.sleep

    def run_profile(
            self,
            profile: LoopProfile,
            *,
            cycle_fn: Callable[[], dict[str, Any]],
            once: bool = False,
            max_cycles: int | None = None,
            interval_seconds_override: float | None = None,
    ) -> dict[str, Any]:
        completed_cycles: list[dict[str, Any]] = []
        interval_seconds = interval_seconds_override
        if interval_seconds is None:
            interval_seconds = cadence_to_interval_seconds(profile.cadence)

        while True:
            completed_cycles.append(cycle_fn())
            if once:
                break
            if max_cycles is not None and len(completed_cycles) >= max_cycles:
                break
            self.sleep_fn(interval_seconds)

        return {
            "profile_id": profile.profile_id,
            "completed_cycles": len(completed_cycles),
            "interval_seconds": interval_seconds,
            "cycle_summaries": completed_cycles,
        }
