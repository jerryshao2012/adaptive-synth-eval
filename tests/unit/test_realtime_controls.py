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

    # Test single-persona mode - should NOT show persona ID even when set
    controller_single = RealtimeChatController(
        initial_delay_seconds=0.5,
        personas={"P001": {"role": "tester"}},
        single_persona_mode=True,
    )
    controller_single.set_active_persona("P001")
    assert controller_single.prompt_text == "⚡> "  # No persona ID shown in single-persona mode
