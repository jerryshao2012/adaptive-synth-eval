from adaptive_synth_eval.scoring.failure_modes import detect_failure_mode
from adaptive_synth_eval.scoring.response_quality import score_response


def test_score_response_returns_nullable_scores_without_context():
    score = score_response(user_message="hello", bot_response="hi", expected_context=None)

    assert score.groundedness_score is None
    assert score.relevance_score is not None
    assert score.safety_score is not None
    assert score.tool_correctness is None


def test_detect_failure_mode_identifies_empty_response():
    assert detect_failure_mode("", error=None) == "empty_response"
    assert detect_failure_mode("ok", error="timeout") == "endpoint_error"
