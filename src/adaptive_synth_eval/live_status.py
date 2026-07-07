from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field, replace
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


@dataclass
class LiveStatusSnapshot:
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


def format_status_line(snapshot: LiveStatusSnapshot) -> str:
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
    return " | ".join(parts)


class LiveStatusBar:
    def __init__(self, *, title: str = "ASE", enabled: bool | None = None) -> None:
        self._enabled = sys.stdout.isatty() if enabled is None else bool(enabled)
        self._console = Console(file=sys.stdout, force_terminal=self._enabled)
        self._title = title
        self._snapshot = LiveStatusSnapshot()
        self._live: Live | None = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> bool:
        if not self._enabled or self._live is not None:
            return self._enabled
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
            transient=True,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._live.start()
        return True

    def update(self, **changes: Any) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._snapshot = replace(self._snapshot, **changes)
            live = self._live
        if live is not None:
            live.update(self._render())

    def stop(self) -> None:
        live = self._live
        self._live = None
        if live is not None:
            live.stop()

    def _render(self) -> Panel:
        return Panel(Text(format_status_line(self._snapshot)), title=self._title, border_style="cyan", expand=True)
