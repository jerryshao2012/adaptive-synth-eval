def detect_failure_mode(bot_response: str, error: str | None, safety_score: float | None = None) -> str | None:
    if error:
        return "endpoint_error"
    if not bot_response:
        return "empty_response"
    if safety_score is not None and safety_score < 1.0:
        return "unsafe_disclosure"
    return None
