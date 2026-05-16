from adaptive_synth_eval.clients.chatbot import ChatbotClient, ChatbotResponse


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
