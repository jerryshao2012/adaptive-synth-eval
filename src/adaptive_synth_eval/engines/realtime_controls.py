from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import redirect_stderr
from dataclasses import dataclass
from typing import Any

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.patch_stdout import patch_stdout
except Exception:  # pragma: no cover - optional dependency fallback
    PromptSession = None
    patch_stdout = None

logger = logging.getLogger(__name__)


@dataclass
class RealtimeControlState:
    delay_seconds: float
    paused: bool = False
    stop_requested: bool = False
    behavior_mode: str = "default"


class RealtimeChatController:
    """Manage ephemeral runtime controls for realtime chat playback."""

    SUPPORTED_BEHAVIORS = {
        "default",
        "aggressive",
        "polite",
        "concise",
        "confused",
        "anxious",
    }

    COMMAND_HELP = (
        "Realtime controls: [h]elp, [s]tatus, [+] faster, [-] slower, "
        "[p]ause/resume, [q]uit, style <default|aggressive|polite|concise|confused|anxious>"
    )
    PROMPT_TEXT = "⚡> "

    def __init__(
            self,
            *,
            initial_delay_seconds: float = 0.8,
            delay_step_seconds: float = 0.25,
            min_delay_seconds: float = 0.0,
            max_delay_seconds: float = 5.0,
    ) -> None:
        self._delay_step_seconds = delay_step_seconds
        self._min_delay_seconds = min_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._state = RealtimeControlState(
            delay_seconds=max(min_delay_seconds, min(max_delay_seconds, initial_delay_seconds))
        )
        self._lock = threading.Lock()
        self._paused_event = threading.Event()
        self._stop_event = threading.Event()
        self._input_thread: threading.Thread | None = None
        self._patched_logging_handlers: list[tuple[logging.StreamHandler[Any], Any]] = []
        self._temporary_logger_levels: list[tuple[logging.Logger, int]] = []
        # Default keeps INFO logs visible; set REALTIME_SUPPRESS_INFO_LOGS=true to silence noisy transport logs.
        self._suppress_info_logs = os.getenv("REALTIME_SUPPRESS_INFO_LOGS", "false").lower() in {
            "1", "true", "yes", "y"
        }

    @property
    def current_delay_seconds(self) -> float:
        with self._lock:
            return self._state.delay_seconds

    @property
    def is_paused(self) -> bool:
        return self._paused_event.is_set()

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    @property
    def behavior_mode(self) -> str:
        with self._lock:
            return self._state.behavior_mode

    def start(self) -> bool:
        """Start background command listener if stdin supports interactive input."""
        if not sys.stdin.isatty():
            logger.warning("Realtime controls unavailable: stdin is not interactive. Continuing without controls.")
            return False

        self._patch_logging_streams_for_prompt()
        if self._suppress_info_logs:
            self._reduce_noisy_loggers_for_interactive_prompt()
        self._input_thread = threading.Thread(target=self._input_loop, name="realtime-chat-controls", daemon=True)
        self._input_thread.start()
        logger.info(self.COMMAND_HELP)
        logger.info("Type a command and press Enter while realtime chat is running.")
        return True

    def stop(self) -> None:
        with self._lock:
            self._state.stop_requested = True
            self._state.paused = False
        self._stop_event.set()
        self._paused_event.clear()
        self._restore_logging_streams()
        if self._suppress_info_logs:
            self._restore_logger_levels()

    def apply_command(self, command: str) -> str:
        """Apply a command and return a status line suitable for console output."""
        normalized = command.strip().lower()
        if normalized in {"h", "help"}:
            return self.COMMAND_HELP
        if normalized in {"s", "status"}:
            return self._status_text()
        if normalized.startswith("style ") or normalized.startswith("behavior "):
            parts = normalized.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: style <default|aggressive|polite|concise|confused|anxious>"
            requested = parts[1].strip()
            return self._set_behavior_mode(requested)
        if normalized in {"style", "behavior", "mode"}:
            return "Usage: style <default|aggressive|polite|concise|confused|anxious>"
        if normalized in {"+", "f", "faster"}:
            with self._lock:
                self._state.delay_seconds = max(
                    self._min_delay_seconds,
                    self._state.delay_seconds - self._delay_step_seconds,
                )
            return self._status_text(prefix="Playback speed increased")
        if normalized in {"-", "l", "slower"}:
            with self._lock:
                self._state.delay_seconds = min(
                    self._max_delay_seconds,
                    self._state.delay_seconds + self._delay_step_seconds,
                )
            return self._status_text(prefix="Playback speed decreased")
        if normalized in {"p", "pause"}:
            if self._paused_event.is_set():
                self._paused_event.clear()
                with self._lock:
                    self._state.paused = False
                return self._status_text(prefix="Playback resumed")
            self._paused_event.set()
            with self._lock:
                self._state.paused = True
            return self._status_text(prefix="Playback paused")
        if normalized in {"r", "resume"}:
            self._paused_event.clear()
            with self._lock:
                self._state.paused = False
            return self._status_text(prefix="Playback resumed")
        if normalized in {"q", "quit", "stop", "exit"}:
            with self._lock:
                self._state.stop_requested = True
            self._paused_event.clear()
            self._stop_event.set()
            return "Stop requested. Finishing current turn and ending realtime run."
        if not normalized:
            return ""
        return f"Unknown command: {command}. Type 'h' for help."

    def wait_if_paused(self) -> bool:
        """Block while paused. Return False if stop requested."""
        while self._paused_event.is_set() and not self._stop_event.is_set():
            time.sleep(0.05)
        return not self._stop_event.is_set()

    def wait_for_turn_delay(self) -> bool:
        """Wait between turns while allowing pause/stop controls to take effect quickly."""
        target = self.current_delay_seconds
        if target <= 0:
            return not self._stop_event.is_set()

        elapsed = 0.0
        tick = 0.05
        while elapsed < target:
            if self._stop_event.is_set():
                return False
            if self._paused_event.is_set() and not self.wait_if_paused():
                return False
            sleep_for = min(tick, target - elapsed)
            time.sleep(sleep_for)
            elapsed += sleep_for
        return not self._stop_event.is_set()

    def _status_text(self, *, prefix: str = "Status") -> str:
        paused_text = "paused" if self._paused_event.is_set() else "running"
        return (
            f"{prefix}: delay={self.current_delay_seconds:.2f}s, "
            f"mode={paused_text}, behavior={self.behavior_mode}"
        )

    def _set_behavior_mode(self, requested: str) -> str:
        if requested not in self.SUPPORTED_BEHAVIORS:
            supported = ", ".join(sorted(self.SUPPORTED_BEHAVIORS))
            return f"Unsupported behavior: {requested}. Supported: {supported}"

        with self._lock:
            self._state.behavior_mode = requested

        return self._status_text(prefix="Behavior updated")

    def _input_loop(self) -> None:
        if PromptSession is None or patch_stdout is None:
            self._input_loop_basic()
            return

        import sys

        session = PromptSession()
        while not self._stop_event.is_set():
            try:
                # Keep the prompt stable while concurrent stdout/stderr lines are printed.
                with patch_stdout(raw=True), redirect_stderr(sys.stdout):
                    raw = session.prompt(self.PROMPT_TEXT)
            except EOFError:
                return
            except KeyboardInterrupt:
                self._stop_event.set()
                return

            message = self.apply_command(raw)
            if message:
                logger.info(message)

    def _input_loop_basic(self) -> None:
        """Fallback line input when prompt_toolkit is unavailable."""
        while not self._stop_event.is_set():
            try:
                raw = input(self.PROMPT_TEXT)
            except EOFError:
                return
            except KeyboardInterrupt:
                self._stop_event.set()
                return

            message = self.apply_command(raw)
            if message:
                logger.info(message)

    def _patch_logging_streams_for_prompt(self) -> None:
        """Route logger streams through current stdout so prompt_toolkit can redraw safely."""
        if self._patched_logging_handlers:
            return

        root_logger = logging.getLogger()
        candidate_loggers = [root_logger]
        for logger_obj in logging.root.manager.loggerDict.values():
            if isinstance(logger_obj, logging.Logger):
                candidate_loggers.append(logger_obj)

        seen_handlers: set[int] = set()
        for logger_obj in candidate_loggers:
            for handler in logger_obj.handlers:
                if not isinstance(handler, logging.StreamHandler):
                    continue
                if id(handler) in seen_handlers:
                    continue
                seen_handlers.add(id(handler))
                original_stream = handler.stream
                handler.setStream(_PromptFriendlyLogStream())
                self._patched_logging_handlers.append((handler, original_stream))

    def _restore_logging_streams(self) -> None:
        for handler, original_stream in self._patched_logging_handlers:
            handler.setStream(original_stream)
        self._patched_logging_handlers.clear()

    def _reduce_noisy_loggers_for_interactive_prompt(self) -> None:
        """Temporarily suppress noisy INFO logs while the prompt is active."""
        if self._temporary_logger_levels:
            return

        for logger_name in (
                "adaptive_synth_eval.clients.chatbot",
                "urllib3",
        ):
            logger_obj = logging.getLogger(logger_name)
            current_effective = logger_obj.getEffectiveLevel()
            if current_effective < logging.WARNING:
                self._temporary_logger_levels.append((logger_obj, logger_obj.level))
                logger_obj.setLevel(logging.WARNING)

    def _restore_logger_levels(self) -> None:
        for logger_obj, original_level in self._temporary_logger_levels:
            logger_obj.setLevel(original_level)
        self._temporary_logger_levels.clear()


class _PromptFriendlyLogStream:
    """Stream wrapper that writes to current stdout (prompt-aware when patched)."""

    def __init__(self):
        self._lock = threading.Lock()

    def write(self, text):
        if text is None:
            return 0
        value = str(text)
        if not value:
            return 0

        import sys

        with self._lock:
            return sys.stdout.write(value)

    def flush(self):
        import sys

        return sys.stdout.flush()

    def __getattr__(self, item):
        import sys

        return getattr(sys.stdout, item)
