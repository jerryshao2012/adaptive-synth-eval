"""Observed target reliability must not be confused with evaluator runtime."""

from adaptive_synth_eval.monitoring.runner import _observed_reliability


def test_observed_reliability_maps_target_telemetry() -> None:
    reliability = _observed_reliability(
        {
            "latency_ms": 1234,
            "guardrail_latency_ms": 22,
            "availability": True,
            "trace_errors": ["span failed"],
            "tool_errors": 2,
            "bot_response": "ok",
        }
    )

    assert reliability["target_latency_ms"] == 1234
    assert reliability["guardrail_latency_ms"] == 22
    assert reliability["availability"] == 1.0
    assert reliability["trace_error_count"] == 1
    assert reliability["tool_error_count"] == 2


def test_error_wins_over_conflicting_availability_evidence() -> None:
    reliability = _observed_reliability(
        {
            "error": "timeout",
            "availability": True,
            "status_code": 200,
            "bot_response": "ok",
        }
    )
    assert reliability["availability"] == 0.0
    assert reliability["availability_status"] == "fail"
    assert reliability["availability_evidence"] == "error"


def test_availability_precedence_and_unknowns() -> None:
    assert _observed_reliability({"availability": False, "status_code": 200})[
        "availability"
    ] == 0.0
    assert _observed_reliability({"status_code": 503, "bot_response": "text"})[
        "availability"
    ] == 0.0
    assert _observed_reliability({"bot_response": "text"})["availability"] == 1.0

    unknown = _observed_reliability({})
    assert unknown["availability"] is None
    assert unknown["target_latency_ms"] is None
    assert unknown["availability_status"] == "unknown"


def test_nested_response_telemetry_is_used_without_overriding_top_level_error() -> None:
    reliability = _observed_reliability(
        {
            "bot_response": "an error body still arrived",
            "response_raw": {
                "status_code": 503,
                "telemetry": {
                    "target_latency_ms": 321,
                    "guardrail_latency_ms": 12,
                    "trace_errors": ["trace failed"],
                    "tool_errors": ["tool failed"],
                },
            },
        }
    )
    assert reliability["availability"] == 0.0
    assert reliability["availability_evidence"] == "http_status"
    assert reliability["target_latency_ms"] == 321
    assert reliability["guardrail_latency_ms"] == 12
    assert reliability["trace_error_count"] == 1
    assert reliability["tool_error_count"] == 1

    explicit_error = _observed_reliability(
        {
            "error": "timeout",
            "response_raw": {"status_code": 200, "availability": True},
        }
    )
    assert explicit_error["availability_evidence"] == "error"
