from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass
class PromptToolkitStatusSnapshot:
    phase: str = "running"
    completed: int = 0
    total: int | None = None
    last_item: str | None = None
    elapsed_seconds: float | None = None
    eta_seconds: float | None = None
    errors: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0.0, float(seconds))
    whole_seconds = int(round(seconds))
    minutes, secs = divmod(whole_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_status_line(snapshot: PromptToolkitStatusSnapshot, *, title: str = "ASE RUN") -> str:
    if snapshot.total is None:
        done_text = f"done={snapshot.completed}"
    else:
        done_text = f"done={snapshot.completed}/{snapshot.total}"

    parts = [snapshot.phase, done_text]
    if snapshot.last_item:
        parts.append(f"last={snapshot.last_item}")
    parts.append(f"elapsed={_format_duration(snapshot.elapsed_seconds)}")
    parts.append(f"eta={_format_duration(snapshot.eta_seconds)}")
    if snapshot.errors is not None:
        parts.append(f"errors={snapshot.errors}")
    for key, value in snapshot.details.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return f"[{title}] " + " | ".join(parts)


class PromptToolkitStatusBar:
    """PromptToolkit-native status source for bottom toolbar rendering.

    The prompt loop owns terminal rendering; this class only stores snapshot data
    and requests a toolbar redraw via callback.
    """

    def __init__(self, *, title: str = "ASE RUN", enabled: bool = True) -> None:
        self._title = title
        self._enabled = bool(enabled)
        self._snapshot = PromptToolkitStatusSnapshot()
        self._lock = threading.Lock()
        self._invalidate: Any | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> bool:
        return self._enabled

    def stop(self) -> None:
        return

    def update(self, **changes: Any) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._snapshot = replace(self._snapshot, **changes)
            invalidate = self._invalidate
        if invalidate is not None:
            invalidate()

    def bind_invalidate(self, invalidate: Any) -> None:
        with self._lock:
            self._invalidate = invalidate

    def render_toolbar(self) -> str:
        with self._lock:
            snapshot = self._snapshot
        return format_status_line(snapshot, title=self._title)
