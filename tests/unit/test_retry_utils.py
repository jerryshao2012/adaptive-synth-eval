import requests

from adaptive_synth_eval.clients.retry_utils import is_transient_error, retry_on_transient


def test_retry_on_transient_retries_timeout_once_then_succeeds():
    calls = {"count": 0}

    @retry_on_transient(max_retries=1, initial_backoff=0.0, max_backoff=0.0, jitter=False)
    def flaky_call():
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.exceptions.ReadTimeout("timed out")
        return "ok"

    assert flaky_call() == "ok"
    assert calls["count"] == 2


def test_is_transient_error_does_not_retry_content_filter():
    error = RuntimeError("blocked by content filter policy")
    assert is_transient_error(error) is False
