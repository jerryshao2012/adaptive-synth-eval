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
