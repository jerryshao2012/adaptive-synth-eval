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
