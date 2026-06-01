import os
from unittest.mock import patch, Mock

import requests

from adaptive_synth_eval.clients.chatbot import ChatbotClient, ChatbotResponse, extract_bot_text


def test_chatbot_response_extracts_known_text_fields():
    response = ChatbotResponse.from_payload({"llm_response": "hello"}, latency_ms=12.3, status_code=200)

    assert response.bot_response == "hello"
    assert response.latency_ms == 12.3
    assert response.error is None


def test_chatbot_client_returns_mock_response_when_disabled():
    client = ChatbotClient(enabled=False)

    response = client.send(
        conversation_id="c1",
        session_id="s1",
        turn_id=1,
        user_message="What is parental leave?",
    )

    assert response.bot_response
    assert response.status_code == 0
    assert response.raw["mock"] is True


def test_chatbot_client_returns_error_when_enabled_but_endpoint_missing():
    with patch.dict(os.environ, {"CHATBOT_ENDPOINT": ""}, clear=False):
        client = ChatbotClient(enabled=True)

        response = client.send(
            conversation_id="c1",
            session_id="s1",
            turn_id=1,
            user_message="What is parental leave?",
        )

    assert response.status_code == 0
    assert response.error == "Chatbot endpoint is not configured"
    assert response.raw == {}


def test_chatbot_client_init_defaults():
    with patch.dict(os.environ, {"CHATBOT_ENDPOINT": "http://env-endpoint", "CHATBOT_TIMEOUT": "42.0"}):
        client = ChatbotClient(enabled=True)
        assert client.endpoint == "http://env-endpoint"
        assert client.timeout_seconds == 42.0


def test_chatbot_client_init_overrides():
    client = ChatbotClient(endpoint="http://custom", timeout_seconds=10.0)
    assert client.endpoint == "http://custom"
    assert client.timeout_seconds == 10.0


@patch("adaptive_synth_eval.clients.chatbot.requests.post")
def test_chatbot_client_send_success(mock_post):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.ok = True
    mock_response.json.return_value = {"response": "mocked success", "retrieved_policy_ids": ["p1"]}
    mock_post.return_value = mock_response

    client = ChatbotClient(endpoint="http://test", enabled=True)
    res = client.send(
        conversation_id="c1",
        session_id="s1",
        turn_id=1,
        user_message="test message",
    )

    assert res.status_code == 200
    assert res.bot_response == "mocked success"
    assert res.retrieved_policy_ids == ["p1"]
    mock_post.assert_called_once()


@patch("adaptive_synth_eval.clients.chatbot.requests.post")
def test_chatbot_client_send_failure_fallback_text(mock_post):
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.ok = False
    mock_response.json.side_effect = ValueError("Invalid JSON")
    mock_response.text = "Internal Server Error"
    mock_post.return_value = mock_response

    client = ChatbotClient(endpoint="http://test", enabled=True)
    res = client.send(
        conversation_id="c1",
        session_id="s1",
        turn_id=1,
        user_message="test message",
    )

    assert res.status_code == 500
    assert res.error == "HTTP 500"
    assert res.bot_response == "Internal Server Error"


def test_extract_bot_text_all_keys():
    assert extract_bot_text({"response": "val1"}) == "val1"
    assert extract_bot_text({"answer": "val2"}) == "val2"
    assert extract_bot_text({"message": "val3"}) == "val3"
    assert extract_bot_text({"content": "val4"}) == "val4"
    assert extract_bot_text({"text": "val5"}) == "val5"
    assert extract_bot_text({"llm_response": "val6"}) == "val6"
    assert extract_bot_text({"unknown": "val7"}) == ""


@patch("adaptive_synth_eval.clients.chatbot.requests.post")
def test_chatbot_client_retries_read_timeout_then_succeeds(mock_post):
    success_response = Mock()
    success_response.status_code = 200
    success_response.ok = True
    success_response.json.return_value = {"response": "recovered"}

    mock_post.side_effect = [
        requests.exceptions.ReadTimeout("read timed out"),
        success_response,
    ]

    client = ChatbotClient(
        endpoint="http://test",
        enabled=True,
        retry_max_retries=1,
        retry_initial_backoff=0.0,
        retry_max_backoff=0.0,
        retry_jitter=False,
        retry_on_timeout=True,
    )

    res = client.send(
        conversation_id="c1",
        session_id="s1",
        turn_id=1,
        user_message="test message",
    )

    assert res.status_code == 200
    assert res.bot_response == "recovered"
    assert mock_post.call_count == 2


@patch("adaptive_synth_eval.clients.chatbot.requests.post")
def test_chatbot_client_timeout_exhaustion_returns_error(mock_post):
    mock_post.side_effect = requests.exceptions.ReadTimeout("read timed out")

    client = ChatbotClient(
        endpoint="http://test",
        enabled=True,
        retry_max_retries=1,
        retry_initial_backoff=0.0,
        retry_max_backoff=0.0,
        retry_jitter=False,
        retry_on_timeout=True,
    )

    res = client.send(
        conversation_id="c1",
        session_id="s1",
        turn_id=1,
        user_message="test message",
    )

    assert res.status_code == 0
    assert "timed out" in (res.error or "")
    assert mock_post.call_count == 2
