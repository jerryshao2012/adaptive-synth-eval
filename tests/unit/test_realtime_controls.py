import asyncio
import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController


@pytest.mark.asyncio
async def test_async_listener_is_cancelled_awaited_and_restartable(monkeypatch):
    import adaptive_synth_eval.engines.realtime_controls as controls

    prompts_started = 0

    class FakePromptSession:
        def __init__(self, **kwargs):
            self.app = SimpleNamespace(invalidate=lambda: None)

        async def prompt_async(self, prompt):
            nonlocal prompts_started
            prompts_started += 1
            await asyncio.Event().wait()

    monkeypatch.setattr(controls, "PromptSession", FakePromptSession)
    monkeypatch.setattr(controls, "patch_stdout", lambda **kwargs: nullcontext())
    monkeypatch.setattr(controls.sys.stdin, "isatty", lambda: True)

    controller = RealtimeChatController(initial_delay_seconds=0)
    assert await controller.start_async() is True
    await asyncio.sleep(0)
    listener = controller._input_task
    controller.stop()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert listener is not None and listener.done()
    await controller.stop_async()

    assert prompts_started == 1
    assert controller._input_task is None
    assert not any(
        thread.name == "realtime-chat-controls" and thread.is_alive()
        for thread in threading.enumerate()
    )

    assert await controller.start_async() is True
    await asyncio.sleep(0)
    await controller.stop_async()
    assert prompts_started == 2


def test_realtime_controller_speed_commands_adjust_delay():
    controller = RealtimeChatController(
        initial_delay_seconds=1.0, delay_step_seconds=0.25
    )

    controller.apply_command("+")
    assert controller.current_delay_seconds == 0.75

    controller.apply_command("-")
    assert controller.current_delay_seconds == 1.0

    controller.apply_command("slower")
    assert controller.current_delay_seconds == 1.25


def test_realtime_controller_pause_resume_and_stop():
    controller = RealtimeChatController(initial_delay_seconds=0.5)

    controller.apply_command("pause")
    assert controller.is_paused is True

    controller.apply_command("resume")
    assert controller.is_paused is False

    message = controller.apply_command("stop")
    assert "Stop requested" in message
    assert controller.stop_requested is True


def test_realtime_controller_style_command_updates_behavior_mode():
    controller = RealtimeChatController(initial_delay_seconds=0.5)

    message = controller.apply_command("style aggressive")

    assert "Behavior updated" in message
    assert controller.behavior_mode == "aggressive"


def test_realtime_controller_per_persona_behavior_modes():
    """Test that style commands apply to active persona specifically."""
    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    # Initially no active persona, style command is rejected
    msg = controller.apply_command("style aggressive")
    assert "No active persona selected" in msg
    assert controller.behavior_mode == "default"

    # Set active persona and apply style
    controller.set_active_persona("P1")
    msg = controller.apply_command("style polite")
    assert "Behavior updated for P1" in msg

    # Verify P1 has its own behavior mode
    assert controller.get_behavior_for_persona("P1") == "polite"

    # Switch to P2 and set different style
    controller.set_active_persona("P2")
    msg = controller.apply_command("style concise")
    assert "Behavior updated for P2" in msg

    # Verify P2 has its own behavior mode
    assert controller.get_behavior_for_persona("P2") == "concise"

    # Verify P1 still has its original behavior
    assert controller.get_behavior_for_persona("P1") == "polite"

    # Switch back to P1 and verify it retains its behavior
    controller.set_active_persona("P1")
    assert controller.get_behavior_for_persona() == "polite"

    # Verify the internal status text shows correct behavior for active persona.
    status = controller._status_text()
    assert "behavior=polite" in status
    assert "persona=P1" in status


def test_realtime_controller_get_behavior_for_persona():
    """Test the get_behavior_for_persona method with various scenarios."""
    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    # No active persona, no persona-specific behaviors - should return global default
    assert controller.get_behavior_for_persona() == "default"
    assert controller.get_behavior_for_persona("P1") == "default"

    # Style command requires an active persona in multi-persona mode
    msg = controller.apply_command("style aggressive")
    assert "No active persona selected" in msg
    assert controller.get_behavior_for_persona("P1") == "default"

    # Set persona-specific behavior for P1 and P2 independently
    controller.set_active_persona("P1")
    controller.apply_command("style polite")
    controller.set_active_persona("P2")
    controller.apply_command("style aggressive")

    # P1 should have its own behavior
    assert controller.get_behavior_for_persona("P1") == "polite"
    # P2 should have its own behavior
    assert controller.get_behavior_for_persona("P2") == "aggressive"
    # Active persona query returns P2's behavior
    assert controller.get_behavior_for_persona() == "aggressive"


def test_realtime_controller_status_text_shows_persona_behavior():
    """Test that the internal status text shows the correct behavior for active persona."""
    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    # Status should show default behavior when no active persona
    status = controller._status_text()
    assert "behavior=default" in status
    assert "persona=none" in status

    # Set active persona with different behavior
    controller.set_active_persona("P1")
    controller.apply_command("style polite")

    # Status should show P1's specific behavior
    status = controller._status_text()
    assert "behavior=polite" in status
    assert "persona=P1" in status

    # Switch to P2 (no override yet, should show default)
    controller.set_active_persona("P2")
    status = controller._status_text()
    assert "behavior=default" in status
    assert "persona=P2" in status


def test_realtime_controller_style_requires_active_persona_in_multi_persona_mode():
    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    message = controller.apply_command("style polite")

    assert "No active persona selected" in message
    assert controller.behavior_mode == "default"
    assert controller.get_behavior_for_persona("P1") == "default"
    assert controller.get_behavior_for_persona("P2") == "default"


def test_realtime_controller_notify_conversation_complete_logs_completion():
    """notify_conversation_complete tracks counts and logs when all convos done."""
    personas = {"P1": {}, "P2": {}}
    persona_total_convos = {"P1": 2, "P2": 1}
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas=personas,
        persona_total_convos=persona_total_convos,
    )

    # One down for P1 — not all done yet
    controller.notify_conversation_complete("P1")
    with controller._state_cv:
        assert controller._persona_done_convos.get("P1") == 1

    # Second down — all P1 done
    controller.notify_conversation_complete("P1")
    with controller._state_cv:
        assert controller._persona_done_convos.get("P1") == 2

    # P2 done
    controller.notify_conversation_complete("P2")
    with controller._state_cv:
        assert controller._persona_done_convos.get("P2") == 1


def test_realtime_controller_list_shows_active_sessions_with_marker():
    personas = {"P1": {}, "P2": {}, "P3": {}}
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas=personas,
    )
    controller.register_conversation_session("conv_000001", "P1")
    controller.register_conversation_session("conv_000002", "P2")

    msg = controller.apply_command("list")
    assert "*P1-conv_000001" in msg
    assert "P2-conv_000002" in msg


def test_realtime_controller_rejects_unknown_behavior_mode():
    controller = RealtimeChatController(initial_delay_seconds=0.5)

    message = controller.apply_command("style wildly")

    assert "Unsupported behavior" in message
    assert controller.behavior_mode == "default"


def test_realtime_controller_list_and_switching():
    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    controller.register_conversation_session("conv_000001", "P1")
    controller.register_conversation_session("conv_000002", "P2")

    msg = controller.apply_command("list")
    assert "P1-conv_000001" in msg
    assert "P2-conv_000002" in msg

    # explicit session switch (case-insensitive)
    msg = controller.apply_command("switch p2-conv_000002")
    assert "Conversation updated" in msg
    assert controller.active_persona_id == "P2"
    assert controller.active_session_id == "conv_000002"

    msg = controller.apply_command("switch conv_999999")
    assert "Unknown conversation" in msg

    msg = controller.apply_command("persona P1")
    assert "Unknown command" in msg


def test_realtime_command_completer():
    try:
        from prompt_toolkit.document import Document

        from adaptive_synth_eval.engines.realtime_controls import (
            RealtimeChatController,
            RealtimeCommandCompleter,
        )
    except ImportError:
        return  # Skip if prompt_toolkit is not installed

    if RealtimeCommandCompleter is None:
        return  # Skip if prompt_toolkit is not installed

    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
        "P3": {"role": "developer"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)
    completer = RealtimeCommandCompleter(controller)

    # 1. Test top-level commands suggestions
    completions = list(completer.get_completions(Document("l"), None))
    # Should suggest list
    texts = [c.text for c in completions]
    assert "list" in texts

    # 2. Test empty input top-level suggestions
    completions = list(completer.get_completions(Document(""), None))
    texts = [c.text for c in completions]
    assert "help" in texts
    assert "list" in texts

    controller.register_conversation_session("conv_000001", "P1")
    controller.register_conversation_session("conv_000002", "P2")

    # 3. Test switch command
    completions = list(completer.get_completions(Document("switch p"), None))
    texts = [c.text for c in completions]
    assert "P2-conv_000002" in texts
    assert "conv_000002" not in texts

    # 4. Test style/behavior command suggestions (active behavior is "default")
    completions = list(completer.get_completions(Document("style "), None))
    texts = [c.text for c in completions]
    assert "aggressive" in texts
    assert "default" not in texts  # should exclude active behavior

    # 5. Test style/behavior command suggestions with prefix
    completions = list(completer.get_completions(Document("style agg"), None))
    texts = [c.text for c in completions]
    assert texts == ["aggressive"]
    assert completions[0].start_position == -3


def test_realtime_controller_single_persona_mode():
    from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController

    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas=personas,
        single_persona_mode=True,
    )

    # 1. Test command_help doesn't show list/switch controls
    assert "list" not in controller.command_help
    assert "switch" not in controller.command_help

    # 2. Test apply_command returns disabled messages
    msg1 = controller.apply_command("list")
    assert "disabled" in msg1

    msg2 = controller.apply_command("persona P2")
    assert "Unknown command" in msg2

    msg3 = controller.apply_command("switch P1")
    assert "disabled" in msg3

    # 3. Test autocomplete does not suggest persona commands
    try:
        from prompt_toolkit.document import Document

        from adaptive_synth_eval.engines.realtime_controls import (
            RealtimeCommandCompleter,
        )

        if RealtimeCommandCompleter is not None:
            completer = RealtimeCommandCompleter(controller)
            # Test empty input autocomplete
            completions = list(completer.get_completions(Document(""), None))
            texts = [c.text for c in completions]
            assert "list" not in texts
            assert "switch" not in texts

            # Test typed 'switch ' argument autocomplete is empty
            completions = list(completer.get_completions(Document("switch "), None))
            assert len(completions) == 0
    except ImportError:
        pass


def test_realtime_controller_prompt_text_shows_persona():
    """Test that the prompt text dynamically includes the active persona ID in multi-persona mode."""
    from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController

    personas = {
        "P001": {"role": "tester"},
        "P002": {"role": "manager"},
    }

    # Test multi-persona mode (default)
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    # Initially, no persona is set, so prompt should be base only
    assert controller.prompt_text == "⚡> "

    # Set active persona and verify it appears in prompt (multi-persona mode)
    controller.set_active_persona("P001")
    assert controller.prompt_text == "⚡> [P001] "

    # Switch to another persona
    controller.set_active_persona("P002")
    assert controller.prompt_text == "⚡> [P002] "

    # Clear persona (set to None)
    controller.set_active_persona(None)
    assert controller.prompt_text == "⚡> "

    # Test single-persona mode - should still show persona ID when set
    controller_single = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P001": {"role": "tester"}},
        single_persona_mode=True,
    )
    controller_single.set_active_persona("P001")
    assert controller_single.prompt_text == "⚡> [P001] "


def test_realtime_controller_supports_stressed_and_toxic_behaviors():
    controller = RealtimeChatController()

    assert {"stressed", "toxic"} <= controller.SUPPORTED_BEHAVIORS
    usage = controller.apply_command("style")
    assert "stressed" in usage and "toxic" in usage
    assert "Behavior updated" in controller.apply_command("style stressed")
    assert controller.get_behavior_override_for_persona() == "stressed"


def test_switch_without_active_sessions_returns_clear_message():
    controller = RealtimeChatController(
        initial_delay_seconds=0.5, personas={"P1": {}, "P2": {}}
    )

    msg = controller.apply_command("switch P2-conv_000002")

    assert "No active conversation sessions" in msg


def test_realtime_controller_lists_and_switches_session_ids():
    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    controller.register_conversation_session("conv_000001", "P1")
    controller.register_conversation_session("conv_000002", "P2")

    listed = controller.apply_command("list")
    assert "P1-conv_000001" in listed
    assert "P2-conv_000002" in listed

    switched = controller.apply_command("switch P2-conv_000002")
    assert "Conversation updated" in switched
    assert controller.active_persona_id == "P2"
    assert controller.active_session_id == "conv_000002"


def test_realtime_controller_shortcuts_for_list_and_switch():
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P1": {"role": "tester"}, "P2": {"role": "manager"}},
    )
    controller.register_conversation_session("conv_000001", "P1")
    controller.register_conversation_session("conv_000002", "P2")

    listed = controller.apply_command("l")
    assert "P1-conv_000001" in listed
    assert "P2-conv_000002" in listed

    switched = controller.apply_command("s P2-conv_000002")
    assert "Conversation updated" in switched
    assert controller.active_session_id == "conv_000002"


def test_realtime_controller_status_shortcut_is_removed():
    controller = RealtimeChatController(initial_delay_seconds=0.5)

    status = controller.apply_command("st")

    assert "Unknown command" in status


def test_realtime_status_text_includes_conversation_progress_and_eta_fields():
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P1": {}},
        persona_total_convos={"P1": 2},
    )
    controller.register_conversation_session("conv_000001", "P1", total_turns=3)

    status = controller._status_text()
    assert "ts=" in status
    assert "conversations_done=0/2" in status
    assert "conversations_left=2" in status
    assert "eta=unknown" in status

    controller.notify_conversation_complete("P1", "conv_000001")
    status = controller._status_text()
    assert "conversations_done=1/2" in status
    assert "conversations_left=1" in status
    assert "eta=" in status


def test_realtime_controller_persona_command_is_unknown():
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P1": {"role": "tester"}, "P2": {"role": "manager"}},
    )
    controller.register_conversation_session("conv_000001", "P1")
    controller.register_conversation_session("conv_000002", "P1")

    msg = controller.apply_command("persona P2")

    assert "Unknown command" in msg
    assert controller.active_persona_id == "P1"
    assert controller.active_session_id == "conv_000001"


def test_realtime_controller_prompt_text_includes_session_when_active():
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P001": {"role": "tester"}},
    )
    controller.register_conversation_session("conv_000001", "P001")

    assert controller.prompt_text == "⚡> [P001-conv_000001] "


def test_register_conversation_session_does_not_steal_active_session():
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P1": {}, "P2": {}},
    )
    controller.register_conversation_session("conv_000001", "P1")
    controller.register_conversation_session("conv_000002", "P2")

    assert controller.active_session_id == "conv_000001"
    assert controller.active_persona_id == "P1"


def test_realtime_status_text_reports_turn_progress_when_available():
    controller = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P1": {}, "P2": {}},
    )
    controller.register_conversation_session("conv_000001", "P1", total_turns=4)
    controller.register_conversation_session("conv_000002", "P2", total_turns=6)
    controller.notify_turn_complete("conv_000001", count=2)
    controller.notify_turn_complete("conv_000002", count=1)

    status = controller._status_text()

    assert "turns_completed=3" in status
    assert "turns_remaining=7" in status
    assert "active_turns=2/4" in status
