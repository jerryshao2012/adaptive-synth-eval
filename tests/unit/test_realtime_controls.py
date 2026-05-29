from adaptive_synth_eval.engines.realtime_controls import RealtimeChatController


def test_realtime_controller_speed_commands_adjust_delay():
    controller = RealtimeChatController(initial_delay_seconds=1.0, delay_step_seconds=0.25)

    controller.apply_command("+")
    assert controller.current_delay_seconds == 0.75

    controller.apply_command("-")
    assert controller.current_delay_seconds == 1.0


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

    # Initially no active persona, style applies globally
    msg = controller.apply_command("style aggressive")
    assert "Behavior updated (global)" in msg
    assert controller.behavior_mode == "aggressive"

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

    # Verify status shows correct behavior for active persona
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

    # Set global behavior
    controller.apply_command("style aggressive")
    assert controller.get_behavior_for_persona() == "aggressive"
    assert controller.get_behavior_for_persona("P1") == "aggressive"

    # Set persona-specific behavior for P1
    controller.set_active_persona("P1")
    controller.apply_command("style polite")

    # P1 should have its own behavior
    assert controller.get_behavior_for_persona("P1") == "polite"
    # P2 should fall back to global
    assert controller.get_behavior_for_persona("P2") == "aggressive"
    # Active persona query returns P1's behavior
    assert controller.get_behavior_for_persona() == "polite"


def test_realtime_controller_status_shows_persona_behavior():
    """Test that status command shows the correct behavior for active persona."""
    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    # Set global behavior
    controller.apply_command("style aggressive")

    # Status should show global behavior when no active persona
    status = controller._status_text()
    assert "behavior=aggressive" in status
    assert "persona=none" in status

    # Set active persona with different behavior
    controller.set_active_persona("P1")
    controller.apply_command("style polite")

    # Status should show P1's specific behavior
    status = controller._status_text()
    assert "behavior=polite" in status
    assert "persona=P1" in status

    # Switch to P2 (should use global since P2 has no specific behavior)
    controller.set_active_persona("P2")
    status = controller._status_text()
    assert "behavior=aggressive" in status  # Falls back to global
    assert "persona=P2" in status


def test_realtime_controller_rejects_unknown_behavior_mode():
    controller = RealtimeChatController(initial_delay_seconds=0.5)

    message = controller.apply_command("style wildly")

    assert "Unsupported behavior" in message
    assert controller.behavior_mode == "default"


def test_realtime_controller_personas_listing_and_switching():
    personas = {
        "P1": {"role": "tester"},
        "P2": {"role": "manager"},
    }
    controller = RealtimeChatController(initial_delay_seconds=0.5, personas=personas)

    # test personas listing
    msg = controller.apply_command("personas")
    assert "P1" in msg
    assert "P2" in msg

    # test initial active persona is None
    assert controller.active_persona_id is None

    # test set_active_persona programmatically
    controller.set_active_persona("P1")
    assert controller.active_persona_id == "P1"

    # test switching to existing persona (case-insensitive)
    msg = controller.apply_command("persona p2")
    assert "Persona updated" in msg
    assert controller.active_persona_id == "P2"

    # test switching to non-existing persona
    msg = controller.apply_command("persona P3")
    assert "Unknown persona: P3" in msg
    assert controller.active_persona_id == "P2"  # remains unchanged

    # test invalid usage format
    msg = controller.apply_command("persona")
    assert "Usage: persona" in msg


def test_realtime_command_completer():
    try:
        from prompt_toolkit.document import Document
        from adaptive_synth_eval.engines.realtime_controls import RealtimeCommandCompleter, RealtimeChatController
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
    completions = list(completer.get_completions(Document("per"), None))
    # Should suggest "personas" and "persona"
    texts = [c.text for c in completions]
    assert "persona" in texts
    assert "personas" in texts
    # start_position should be -3 because "per" has length 3
    assert completions[0].start_position == -3

    # 2. Test empty input top-level suggestions
    completions = list(completer.get_completions(Document(""), None))
    texts = [c.text for c in completions]
    assert "help" in texts
    assert "persona" in texts

    # 3. Test persona suggestions (active persona is None)
    completions = list(completer.get_completions(Document("persona "), None))
    texts = [c.text for c in completions]
    assert set(texts) == {"P1", "P2", "P3"}
    assert completions[0].start_position == 0

    # 4. Test persona suggestions with prefix
    completions = list(completer.get_completions(Document("persona p"), None))
    texts = [c.text for c in completions]
    assert set(texts) == {"P1", "P2", "P3"}
    assert completions[0].start_position == -1

    # 5. Test persona suggestions when active persona is P1 (should exclude P1)
    controller.set_active_persona("P1")
    completions = list(completer.get_completions(Document("persona "), None))
    texts = [c.text for c in completions]
    assert set(texts) == {"P2", "P3"}

    # 6. Test switch command
    completions = list(completer.get_completions(Document("switch p"), None))
    texts = [c.text for c in completions]
    assert set(texts) == {"P2", "P3"}

    # 7. Test style/behavior command suggestions (active behavior is "default")
    completions = list(completer.get_completions(Document("style "), None))
    texts = [c.text for c in completions]
    assert "aggressive" in texts
    assert "default" not in texts  # should exclude active behavior

    # 8. Test style/behavior command suggestions with prefix
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

    # 1. Test command_help doesn't show persona controls
    assert "persona" not in controller.command_help

    # 2. Test apply_command returns disabled messages
    msg1 = controller.apply_command("personas")
    assert "disabled" in msg1

    msg2 = controller.apply_command("persona P2")
    assert "disabled" in msg2

    msg3 = controller.apply_command("switch P1")
    assert "disabled" in msg3

    # 3. Test autocomplete does not suggest persona commands
    try:
        from prompt_toolkit.document import Document
        from adaptive_synth_eval.engines.realtime_controls import RealtimeCommandCompleter

        if RealtimeCommandCompleter is not None:
            completer = RealtimeCommandCompleter(controller)
            # Test empty input autocomplete
            completions = list(completer.get_completions(Document(""), None))
            texts = [c.text for c in completions]
            assert "personas" not in texts
            assert "persona" not in texts
            assert "switch" not in texts

            # Test typed 'persona ' argument autocomplete is empty
            completions = list(completer.get_completions(Document("persona "), None))
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
