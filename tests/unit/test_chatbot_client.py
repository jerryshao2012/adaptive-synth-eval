import json
import os
import uuid
from unittest.mock import patch, Mock

import httpx
import requests

from adaptive_synth_eval.clients.agentcore_chatbot import AgentCoreChatbotClient
from adaptive_synth_eval.clients.browser_chatbot import BrowserChatbotClient
from adaptive_synth_eval.clients.chatbot import ChatbotClient, ChatbotResponse, extract_bot_text
from adaptive_synth_eval.clients.chatbot_factory import create_chatbot_client
from adaptive_synth_eval.clients.retry_utils import is_transient_error, retry_on_transient
from adaptive_synth_eval.config.schemas import AgentCoreTarget, BrowserChatbot, TargetChatbot


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
def test_chatbot_client_send_api_key_auth(mock_post):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.ok = True
    mock_response.json.return_value = {"response": "success"}
    mock_post.return_value = mock_response

    # Test default header name (x-api-key)
    with patch.dict(os.environ, {"MY_API_KEY_ENV": "secret-key"}):
        client = ChatbotClient(
            endpoint="http://test",
            enabled=True,
            auth={"type": "api_key", "env_var": "MY_API_KEY_ENV"}
        )
        client.send(
            conversation_id="c1",
            session_id="s1",
            turn_id=1,
            user_message="test",
        )
        headers = mock_post.call_args[1]["headers"]
        assert headers["x-api-key"] == "secret-key"

    # Test custom header name
    mock_post.reset_mock()
    with patch.dict(os.environ, {"MY_API_KEY_ENV": "secret-key"}):
        client = ChatbotClient(
            endpoint="http://test",
            enabled=True,
            auth={"type": "api_key", "env_var": "MY_API_KEY_ENV", "header_name": "custom-auth-header"}
        )
        client.send(
            conversation_id="c1",
            session_id="s1",
            turn_id=1,
            user_message="test",
        )
        headers = mock_post.call_args[1]["headers"]
        assert headers["custom-auth-header"] == "secret-key"


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


# Chatbot Factory Tests Merged
def test_create_chatbot_client_defaults_to_api_client():
    config = TargetChatbot(
        enabled=True,
        endpoint="https://api.example.com/chat",
        retry_max_retries=4,
        retry_initial_backoff_seconds=0.2,
        retry_max_backoff_seconds=2.0,
        retry_backoff_multiplier=1.5,
        retry_jitter=False,
        retry_on_timeout=True,
        retry_on_http_5xx=True,
    )

    client = create_chatbot_client(config)

    assert isinstance(client, ChatbotClient)
    assert client.endpoint == "https://api.example.com/chat"
    assert client.retry_on_timeout is True
    assert client.retry_on_http_5xx is True


def test_create_chatbot_client_uses_browser_client_for_browser_mode():
    config = TargetChatbot(
        enabled=True,
        mode="browser",
        browser=BrowserChatbot(
            url="https://chat.example.com",
            input_selector="textarea",
            submit_selector="button[type='submit']",
            response_selector=".bot-message",
            browser_type="edge",
            headless=True,
        ),
    )

    client = create_chatbot_client(config)

    assert isinstance(client, BrowserChatbotClient)
    assert client.browser_config.browser_type == "edge"


def test_create_chatbot_client_uses_agentcore_client_for_agentcore_mode():
    config = TargetChatbot(
        enabled=True,
        mode="agentcore",
        agentcore=AgentCoreTarget(
            region="us-east-1",
            agent_runtime_arn="arn:aws:bedrock-agentcore:us-east-1:123:runtime/r1",
            qualifier="DEFAULT",
            payload_prompt_key="prompt",
            runtime_session_id_prefix="ase_tfsa_",
        ),
    )

    client = create_chatbot_client(config)

    assert isinstance(client, AgentCoreChatbotClient)
    assert client.region == "us-east-1"


def test_agentcore_client_send_success_parses_response_payload():
    mock_stream = Mock()
    mock_stream.read.return_value = b'{"response":"TFSA limit is $7,000 for 2026"}'

    mock_agentcore_client = Mock()
    mock_agentcore_client.invoke_agent_runtime.return_value = {
        "response": mock_stream,
        "ResponseMetadata": {"HTTPStatusCode": 200},
    }

    client = AgentCoreChatbotClient(
        enabled=True,
        region="us-east-1",
        agent_runtime_arn="arn:aws:bedrock-agentcore:us-east-1:123:runtime/r1",
        payload_prompt_key="prompt",
        runtime_session_id_prefix="ase_tfsa_",
        retry_max_retries=0,
    )
    client._client = mock_agentcore_client

    response = client.send(
        conversation_id="conv_abc",
        session_id="sess_short",
        turn_id=1,
        user_message="What is TFSA limit for 2026?",
    )

    assert response.status_code == 200
    assert "TFSA limit" in response.bot_response
    invoke_kwargs = mock_agentcore_client.invoke_agent_runtime.call_args.kwargs
    assert invoke_kwargs["agentRuntimeArn"].startswith("arn:aws:bedrock-agentcore")
    assert len(invoke_kwargs["runtimeSessionId"]) >= 33
    # Payload forwards the harness session_id and a per-message UUID alongside the prompt.
    sent_payload = json.loads(invoke_kwargs["payload"])
    assert sent_payload["prompt"] == "What is TFSA limit for 2026?"
    assert sent_payload["session_id"] == "sess_short"
    assert uuid.UUID(sent_payload["message_id"])  # parses as a valid UUID


def test_agentcore_client_returns_error_when_runtime_arn_missing():
    client = AgentCoreChatbotClient(enabled=True, agent_runtime_arn=None)

    response = client.send(
        conversation_id="conv_abc",
        session_id="sess_short",
        turn_id=1,
        user_message="Hello",
    )

    assert response.status_code == 0
    assert response.error == "AgentCore runtime ARN is not configured"


# Retry Utils Tests Merged
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


def test_is_transient_error_retries_remote_protocol_disconnects():
    error = httpx.RemoteProtocolError(
        "peer closed connection without sending complete message body (received 0 bytes, expected 34276)"
    )
    assert is_transient_error(error) is True
