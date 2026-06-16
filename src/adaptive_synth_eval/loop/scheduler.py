from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def run_profile(
            self,
            profile: LoopProfile,
            *,
            cycle_fn: Callable[[], dict[str, Any]],
            state_fn: Callable[[LoopProfile], dict[str, Any] | None] | None = None,
            once: bool = False,
            max_cycles: int | None = None,
            interval_seconds_override: float | None = None,
    ) -> dict[str, Any]:
        completed_cycles: list[dict[str, Any]] = []
        interval_seconds = interval_seconds_override
        if interval_seconds is None:
            interval_seconds = cadence_to_interval_seconds(profile.cadence)

        while True:
            state = state_fn(profile) if state_fn is not None else None
            if is_profile_paused(profile, state):
                break
            if not is_within_active_window(profile, now=self.now_fn(), state=state):
                if once:
                    break
                self.sleep_fn(interval_seconds)
                continue
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


@dataclass
class MultiLoopCoordinator:
    sleep_fn: Callable[[float], None] = time.sleep
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def run_profiles(
            self,
            profiles: list[LoopProfile],
            *,
            cycle_fn: Callable[[LoopProfile], dict[str, Any]],
            state_fn: Callable[[LoopProfile], dict[str, Any] | None],
            once: bool = False,
            max_rounds: int | None = None,
            interval_seconds_override: float | None = None,
    ) -> dict[str, Any]:
        next_allowed: dict[str, datetime] = {}
        failure_counts: dict[str, int] = {}
        rounds: list[dict[str, Any]] = []

        while True:
            round_runs: list[dict[str, Any]] = []
            now = self.now_fn()
            ordered = sorted(profiles, key=lambda item: (item.priority, item.profile_id))
            for profile in ordered:
                state = state_fn(profile) or {}
                if is_profile_paused(profile, state):
                    round_runs.append({"profile_id": profile.profile_id, "status": "skipped_paused"})
                    continue
                if not is_within_active_window(profile, now=now, state=state):
                    round_runs.append({"profile_id": profile.profile_id, "status": "skipped_window"})
                    continue
                if now < next_allowed.get(profile.profile_id, now):
                    round_runs.append({"profile_id": profile.profile_id, "status": "skipped_backoff"})
                    continue

                interval_seconds = interval_seconds_override or cadence_to_interval_seconds(profile.cadence)
                try:
                    result = cycle_fn(profile)
                    round_runs.append({"profile_id": profile.profile_id, "status": "completed", "summary": result})
                    failure_counts[profile.profile_id] = 0
                    next_allowed[profile.profile_id] = now + timedelta(seconds=interval_seconds)
                except Exception as exc:
                    failures = failure_counts.get(profile.profile_id, 0) + 1
                    failure_counts[profile.profile_id] = failures
                    next_allowed[profile.profile_id] = now + timedelta(
                        seconds=_backoff_seconds(interval_seconds, failures)
                    )
                    round_runs.append(
                        {
                            "profile_id": profile.profile_id,
                            "status": "failed",
                            "error": str(exc),
                            "failure_count": failures,
                            "next_allowed_at": next_allowed[profile.profile_id].isoformat(),
                        }
                    )

            rounds.append({"started_at": now.isoformat(), "profiles": round_runs})
            if once:
                break
            if max_rounds is not None and len(rounds) >= max_rounds:
                break
            sleep_seconds = interval_seconds_override or _min_interval_seconds(profiles)
            self.sleep_fn(sleep_seconds)

        return {
            "completed_rounds": len(rounds),
            "rounds": rounds,
            "profiles": [profile.profile_id for profile in
                         sorted(profiles, key=lambda item: (item.priority, item.profile_id))],
        }


def is_profile_paused(profile: LoopProfile, state: dict[str, Any] | None) -> bool:
    if profile.paused:
        return True
    return bool((state or {}).get("paused", False))


def is_within_active_window(profile: LoopProfile, *, now: datetime, state: dict[str, Any] | None = None) -> bool:
    windows = list((state or {}).get("active_windows") or profile.active_windows or [])
    if not windows:
        return True
    for window in windows:
        if _window_matches(str(window), now):
            return True
    return False


def _window_matches(window: str, now: datetime) -> bool:
    text = window.strip().upper()
    if not text or text == "ALWAYS":
        return True

    days_part = None
    hours_part = text
    if "@" in text:
        days_part, hours_part = text.split("@", 1)
    if days_part and not _day_matches(days_part, now):
        return False

    match = re.fullmatch(r"(\d{2}:\d{2})-(\d{2}:\d{2})", hours_part)
    if not match:
        raise LoopProfileError(f"Unsupported active window format: {window}")
    start_minutes = _hhmm_to_minutes(match.group(1))
    end_minutes = _hhmm_to_minutes(match.group(2))
    current_minutes = now.hour * 60 + now.minute
    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    return current_minutes >= start_minutes or current_minutes <= end_minutes


def _day_matches(days_part: str, now: datetime) -> bool:
    weekdays = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    current = weekdays[now.weekday()]
    if "-" in days_part:
        start_name, end_name = [item.strip() for item in days_part.split("-", 1)]
        if start_name not in weekdays or end_name not in weekdays:
            raise LoopProfileError(f"Unsupported active window day range: {days_part}")
        start_index = weekdays.index(start_name)
        end_index = weekdays.index(end_name)
        current_index = weekdays.index(current)
        if start_index <= end_index:
            return start_index <= current_index <= end_index
        return current_index >= start_index or current_index <= end_index
    return current == days_part.strip()


def _hhmm_to_minutes(value: str) -> int:
    hours, minutes = value.split(":", 1)
    return int(hours) * 60 + int(minutes)


def _backoff_seconds(base_interval_seconds: float, failure_count: int) -> float:
    return min(base_interval_seconds * (2 ** max(0, failure_count - 1)), base_interval_seconds * 8)


def _min_interval_seconds(profiles: list[LoopProfile]) -> float:
    intervals = [cadence_to_interval_seconds(profile.cadence) for profile in profiles]
    return min(intervals) if intervals else 60.0
