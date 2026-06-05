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
    from prompt_toolkit.completion import Completer, Completion
except Exception:  # pragma: no cover - optional dependency fallback
    PromptSession = None
    patch_stdout = None
    Completer = None
    Completion = None

logger = logging.getLogger(__name__)


@dataclass
class RealtimeControlState:
    delay_seconds: float
    paused: bool = False
    stop_requested: bool = False
    behavior_mode: str = "default"  # Global fallback for backward compatibility
    active_persona_id: str | None = None
    active_session_id: str | None = None
    persona_behavior_modes: dict[str, str] | None = None  # Per-persona behavior tracking


if Completer is not None:
    class RealtimeCommandCompleter(Completer):
        """Autocompleter for realtime control commands."""

        def __init__(self, controller: RealtimeChatController) -> None:
            self.controller = controller

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            word_before = document.get_word_before_cursor()
            text_before = text[:-len(word_before)] if word_before else text
            words_before = text_before.split()

            # Commands to suggest at the top level
            top_level_cmds = [
                "help",
                "status",
                "list",
                "switch",
                "style",
                "behavior",
                "faster",
                "slower",
                "pause",
                "resume",
                "quit",
                "stop",
                "exit",
            ]
            if self.controller._single_persona_mode:
                top_level_cmds = [c for c in top_level_cmds if c not in {"list", "switch"}]

            # Case 1: Typing the command itself
            if len(words_before) == 0:
                prefix = word_before.lower()
                for cmd in top_level_cmds:
                    if not prefix or cmd.startswith(prefix):
                        yield Completion(cmd, start_position=-len(prefix))

            # Case 2: Typing the first argument
            elif len(words_before) == 1:
                cmd = words_before[0].lower()
                prefix = word_before.lower()
                if cmd in {"s", "switch"}:
                    if self.controller._single_persona_mode:
                        return
                    for session_label in self.controller.list_switch_targets():
                        if not prefix or session_label.lower().startswith(prefix):
                            yield Completion(session_label, start_position=-len(prefix))
                elif cmd in {"style", "behavior", "mode"}:
                    current_behavior = self.controller.behavior_mode
                    for behavior in self.controller.SUPPORTED_BEHAVIORS:
                        if behavior != current_behavior and (not prefix or behavior.lower().startswith(prefix)):
                            yield Completion(behavior, start_position=-len(prefix))
else:
    RealtimeCommandCompleter = None


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
        "[p]ause/resume, [q]uit, style <behavior>, list, switch <session_id>"
    )
    PROMPT_TEXT = "⚡> "

    def __init__(
            self,
            *,
            initial_delay_seconds: float = 0.8,
            delay_step_seconds: float = 0.25,
            min_delay_seconds: float = 0.0,
            max_delay_seconds: float = 5.0,
            personas: dict[str, Any] | None = None,
            single_persona_mode: bool = False,
            persona_total_convos: dict[str, int] | None = None,
    ) -> None:
        self._delay_step_seconds = delay_step_seconds
        self._min_delay_seconds = min_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._personas = personas or {}
        self._single_persona_mode = single_persona_mode
        self._persona_total_convos: dict[str, int] = persona_total_convos or {}
        self._persona_done_convos: dict[str, int] = {}
        self._session_personas: dict[str, str] = {}
        self._session_total_turns: dict[str, int] = {}
        self._session_completed_turns: dict[str, int] = {}
        self._active_sessions: set[str] = set()
        self._preferred_persona_id: str | None = None
        if self._single_persona_mode:
            self.command_help = (
                "Realtime controls: [h]elp, [s]tatus, [+] faster, [-] slower, "
                "[p]ause/resume, [q]uit, style <behavior>"
            )
        else:
            self.command_help = self.COMMAND_HELP
        self._state = RealtimeControlState(
            delay_seconds=max(min_delay_seconds, min(max_delay_seconds, initial_delay_seconds)),
            persona_behavior_modes={},
        )
        self._state_cv = threading.Condition(threading.Lock())
        self._input_thread: threading.Thread | None = None
        self._patched_logging_handlers: list[tuple[logging.StreamHandler[Any], Any]] = []
        self._temporary_logger_levels: list[tuple[logging.Logger, int]] = []
        # Default keeps INFO logs visible; set REALTIME_SUPPRESS_INFO_LOGS=true to silence noisy transport logs.
        self._suppress_info_logs = os.getenv("REALTIME_SUPPRESS_INFO_LOGS", "false").lower() in {
            "1", "true", "yes", "y"
        }

    @property
    def current_delay_seconds(self) -> float:
        with self._state_cv:
            return self._state.delay_seconds

    @property
    def is_paused(self) -> bool:
        with self._state_cv:
            return self._state.paused

    @property
    def stop_requested(self) -> bool:
        with self._state_cv:
            return self._state.stop_requested

    @property
    def behavior_mode(self) -> str:
        with self._state_cv:
            return self._state.behavior_mode

    @property
    def active_persona_id(self) -> str | None:
        with self._state_cv:
            return self._state.active_persona_id

    @property
    def active_session_id(self) -> str | None:
        with self._state_cv:
            return self._state.active_session_id

    def set_active_persona(self, persona_id: str | None) -> None:
        with self._state_cv:
            self._preferred_persona_id = persona_id
            self._state.active_persona_id = persona_id
            if persona_id is None:
                self._state.active_session_id = None
                return
            matching = [sid for sid, pid in self._session_personas.items() if
                        pid == persona_id and sid in self._active_sessions]
            if matching:
                self._state.active_session_id = sorted(matching)[0]
            elif self._state.active_session_id and self._state.active_session_id not in self._active_sessions:
                self._state.active_session_id = None

    def register_conversation_session(
            self,
            session_id: str,
            persona_id: str,
            total_turns: int | None = None,
    ) -> None:
        with self._state_cv:
            self._session_personas[session_id] = persona_id
            self._active_sessions.add(session_id)
            if total_turns is not None:
                self._session_total_turns[session_id] = max(0, int(total_turns))
            self._session_completed_turns.setdefault(session_id, 0)
            if self._state.active_session_id is None:
                self._state.active_session_id = session_id
                self._state.active_persona_id = persona_id

    def notify_turn_complete(self, session_id: str, count: int = 1) -> None:
        with self._state_cv:
            if count <= 0:
                return
            self._session_completed_turns[session_id] = self._session_completed_turns.get(session_id, 0) + int(count)

    def is_active_session(self, session_id: str) -> bool:
        with self._state_cv:
            if not self._state.active_session_id:
                return True
            return self._state.active_session_id == session_id

    def notify_conversation_complete(self, persona_id: str, session_id: str | None = None) -> None:
        """Track per-persona/session completion and log when all finish."""
        with self._state_cv:
            self._persona_done_convos[persona_id] = self._persona_done_convos.get(persona_id, 0) + 1
            done = self._persona_done_convos[persona_id]
            total = self._persona_total_convos.get(persona_id, 0)
            if session_id:
                self._active_sessions.discard(session_id)
                if self._state.active_session_id == session_id:
                    self._state.active_session_id = sorted(self._active_sessions)[0] if self._active_sessions else None
                    if self._state.active_session_id:
                        self._state.active_persona_id = self._session_personas.get(self._state.active_session_id)
        if total > 0 and done >= total:
            logger.info("[%s] All %d conversation(s) completed.", persona_id, total)

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
        logger.info(self.command_help)
        logger.info("Type a command and press Enter while realtime chat is running.")
        return True

    def stop(self) -> None:
        with self._state_cv:
            self._state.stop_requested = True
            self._state.paused = False
            self._state_cv.notify_all()
        self._restore_logging_streams()
        if self._suppress_info_logs:
            self._restore_logger_levels()

    def apply_command(self, command: str) -> str:
        """Apply a command and return a status line suitable for console output."""
        normalized = command.strip().lower()
        if normalized in {"h", "help"}:
            return self.command_help
        if normalized in {"st", "status"}:
            return self._status_text()
        if normalized in {"l", "list"}:
            if self._single_persona_mode:
                return "List/switch commands are disabled when running in single-persona mode."
            sessions = self._list_active_sessions()
            if sessions:
                return "Active sessions: " + ", ".join(sessions)
            return "No active conversation sessions."
        if normalized.startswith("switch ") or normalized.startswith("s "):
            if self._single_persona_mode:
                return "List/switch commands are disabled when running in single-persona mode."
            parts = command.strip().split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: switch <persona_id-conversation_id|conversation_id>"
            requested = parts[1].strip()
            return self._set_active_session_by_name(requested)
        if normalized in {"s", "switch"}:
            if self._single_persona_mode:
                return "List/switch commands are disabled when running in single-persona mode."
            return "Usage: switch <persona_id-conversation_id|conversation_id>"
        if normalized.startswith("style ") or normalized.startswith("behavior "):
            parts = normalized.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: style <default|aggressive|polite|concise|confused|anxious>"
            requested = parts[1].strip()
            return self._set_behavior_mode(requested)
        if normalized in {"style", "behavior", "mode"}:
            return "Usage: style <default|aggressive|polite|concise|confused|anxious>"
        if normalized in {"+", "f", "faster"}:
            with self._state_cv:
                self._state.delay_seconds = max(
                    self._min_delay_seconds,
                    self._state.delay_seconds - self._delay_step_seconds,
                )
            return self._status_text(prefix="Playback speed increased")
        if normalized in {"-", "slower"}:
            with self._state_cv:
                self._state.delay_seconds = min(
                    self._max_delay_seconds,
                    self._state.delay_seconds + self._delay_step_seconds,
                )
            return self._status_text(prefix="Playback speed decreased")
        if normalized in {"p", "pause"}:
            with self._state_cv:
                if self._state.paused:
                    self._state.paused = False
                    self._state_cv.notify_all()
                    status_prefix = "Playback resumed"
                else:
                    self._state.paused = True
                    status_prefix = "Playback paused"
            return self._status_text(prefix=status_prefix)
        if normalized in {"r", "resume"}:
            with self._state_cv:
                self._state.paused = False
                self._state_cv.notify_all()
            return self._status_text(prefix="Playback resumed")
        if normalized in {"q", "quit", "stop", "exit"}:
            with self._state_cv:
                self._state.stop_requested = True
                self._state.paused = False
                self._state_cv.notify_all()
            return "Stop requested. Finishing current turn and ending realtime run."
        if not normalized:
            return ""
        return f"Unknown command: {command}. Type 'h' for help."

    def wait_if_paused(self) -> bool:
        """Block while paused. Return False if stop requested."""
        with self._state_cv:
            while self._state.paused and not self._state.stop_requested:
                self._state_cv.wait(timeout=0.05)
            return not self._state.stop_requested

    def wait_for_turn_delay(self) -> bool:
        """Wait between turns while allowing pause/stop controls to take effect quickly."""
        with self._state_cv:
            remaining = self._state.delay_seconds
            if remaining <= 0:
                return not self._state.stop_requested

            tick = 0.05
            while remaining > 0:
                if self._state.stop_requested:
                    return False

                if self._state.paused:
                    self._state_cv.wait_for(
                        lambda: (not self._state.paused) or self._state.stop_requested,
                        timeout=0.05,
                    )
                    continue

                sleep_for = min(tick, remaining)
                start = time.monotonic()
                self._state_cv.wait(timeout=sleep_for)
                elapsed = time.monotonic() - start
                remaining = max(0.0, remaining - elapsed)

            return not self._state.stop_requested

    def _status_text(self, *, prefix: str = "Status") -> str:
        with self._state_cv:
            paused_text = "paused" if self._state.paused else "running"
            delay = self._state.delay_seconds
            persona = self._state.active_persona_id
            session_id = self._state.active_session_id
            if persona and self._state.persona_behavior_modes:
                behavior = self._state.persona_behavior_modes.get(persona, self._state.behavior_mode)
            else:
                behavior = self._state.behavior_mode
            active_slots = len(self._active_sessions)
            progress_suffix = ""
            known_totals = [t for t in self._session_total_turns.values() if t > 0]
            if known_totals:
                total_turns = sum(known_totals)
                completed_turns = sum(
                    min(self._session_completed_turns.get(sid, 0), self._session_total_turns.get(sid, 0))
                    for sid in self._session_total_turns
                )
                remaining_turns = max(0, total_turns - completed_turns)
                progress_suffix = (
                    f", turns_completed={completed_turns}, turns_remaining={remaining_turns}"
                )
                if session_id and session_id in self._session_total_turns:
                    active_total = self._session_total_turns[session_id]
                    active_completed = min(
                        self._session_completed_turns.get(session_id, 0),
                        active_total,
                    )
                    active_remaining = max(0, active_total - active_completed)
                    progress_suffix += (
                        f", active_turns={active_completed}/{active_total}"
                        f" (remaining={active_remaining})"
                    )
        return (
            f"{prefix}: delay={delay:.2f}s, "
            f"mode={paused_text}, behavior={behavior}, persona={persona or 'none'}, "
            f"session={session_id or 'none'}, active_sessions={active_slots}"
            f"{progress_suffix}"
        )

    def _set_behavior_mode(self, requested: str) -> str:
        if requested not in self.SUPPORTED_BEHAVIORS:
            supported = ", ".join(sorted(self.SUPPORTED_BEHAVIORS))
            return f"Unsupported behavior: {requested}. Supported: {supported}"

        status_prefix = "Behavior updated (global)"
        with self._state_cv:
            if self._personas and not self._state.active_persona_id:
                return "No active persona selected. Use: persona <persona_id> before style changes."

            # Apply to active persona if one is set, otherwise use global fallback
            if self._state.active_persona_id:
                persona_id = self._state.active_persona_id
                if self._state.persona_behavior_modes is None:
                    self._state.persona_behavior_modes = {}
                self._state.persona_behavior_modes[persona_id] = requested
                status_prefix = f"Behavior updated for {persona_id}"
            else:
                # No active persona, apply globally (backward compatibility)
                self._state.behavior_mode = requested
        return self._status_text(prefix=status_prefix)

    def list_switch_targets(self) -> list[str]:
        with self._state_cv:
            active_sid = self._state.active_session_id
            labels = []
            for sid in sorted(self._active_sessions):
                persona = self._session_personas.get(sid, "unknown")
                if sid == active_sid:
                    continue
                labels.append(f"{persona}-{sid}")
            return labels

    def _list_active_sessions(self) -> list[str]:
        with self._state_cv:
            active_sid = self._state.active_session_id
            values = []
            for sid in sorted(self._active_sessions):
                persona = self._session_personas.get(sid, "unknown")
                label = f"{persona}-{sid}"
                if sid == active_sid:
                    label = f"*{label}"
                values.append(label)
            return values

    def _set_active_session_by_name(self, requested: str) -> str:
        requested_norm = requested.strip().lower()
        active_labels: list[str] = []
        switched = False
        with self._state_cv:
            if not self._active_sessions:
                # Backward-compatible fallback when sessions aren't registered yet.
                pass
            else:
                direct_match = None
                for sid in self._active_sessions:
                    if sid.lower() == requested_norm:
                        direct_match = sid
                        break
                if direct_match is None:
                    for sid in self._active_sessions:
                        persona = self._session_personas.get(sid, "")
                        label = f"{persona}-{sid}".lower()
                        if label == requested_norm:
                            direct_match = sid
                            break
                if direct_match is None:
                    active_sid = self._state.active_session_id
                    for sid in sorted(self._active_sessions):
                        persona = self._session_personas.get(sid, "unknown")
                        label = f"{persona}-{sid}"
                        if sid == active_sid:
                            label = f"*{label}"
                        active_labels.append(label)
                else:
                    self._state.active_session_id = direct_match
                    persona_id = self._session_personas.get(direct_match)
                    if persona_id:
                        self._state.active_persona_id = persona_id
                        self._preferred_persona_id = persona_id
                    switched = True

        if switched:
            return self._status_text(prefix="Conversation updated")
        if active_labels:
            return f"Unknown conversation: {requested}. Active sessions: {', '.join(active_labels)}"
        return "No active conversation sessions. Use: list"

    @property
    def prompt_text(self) -> str:
        """Generate dynamic prompt text that includes current persona ID if available.

        Include the active persona whenever it is known so realtime sessions that
        are filtered to one persona still show which identity is active.
        """
        base_prompt = self.PROMPT_TEXT
        with self._state_cv:
            active_persona_id = self._state.active_persona_id
            active_session_id = self._state.active_session_id
        if active_persona_id and active_session_id:
            return f"{base_prompt}[{active_persona_id}-{active_session_id}] "
        if active_persona_id:
            return f"{base_prompt}[{active_persona_id}] "
        return base_prompt

    def get_behavior_for_persona(self, persona_id: str | None = None) -> str:
        """Get the behavior mode for a specific persona or the active persona.

        Args:
            persona_id: The persona ID to query. If None, uses the active persona.

        Returns:
            The behavior mode for the persona, or 'default' if not set.
        """
        with self._state_cv:
            target_id = persona_id or self._state.active_persona_id
            if target_id and self._state.persona_behavior_modes:
                return self._state.persona_behavior_modes.get(target_id, self._state.behavior_mode)
            return self._state.behavior_mode  # Fallback to global

    def _input_loop(self) -> None:
        if PromptSession is None or patch_stdout is None:
            self._input_loop_basic()
            return

        completer = RealtimeCommandCompleter(self) if RealtimeCommandCompleter is not None else None
        session = PromptSession(completer=completer, complete_while_typing=True)
        while True:
            with self._state_cv:
                if self._state.stop_requested:
                    break
            try:
                # Keep the prompt stable while concurrent stdout/stderr lines are printed.
                with patch_stdout(raw=True), redirect_stderr(sys.stdout):
                    raw = session.prompt(self.prompt_text)
            except EOFError:
                return
            except KeyboardInterrupt:
                with self._state_cv:
                    self._state.stop_requested = True
                    self._state.paused = False
                    self._state_cv.notify_all()
                return

            message = self.apply_command(raw)
            if message:
                logger.info(message)

    def _input_loop_basic(self) -> None:
        """Fallback line input when prompt_toolkit is unavailable."""
        while True:
            with self._state_cv:
                if self._state.stop_requested:
                    break
            try:
                raw = input(self.prompt_text)
            except EOFError:
                return
            except KeyboardInterrupt:
                with self._state_cv:
                    self._state.stop_requested = True
                    self._state.paused = False
                    self._state_cv.notify_all()
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
