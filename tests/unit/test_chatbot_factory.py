from adaptive_synth_eval.clients.browser_chatbot import BrowserChatbotClient
from adaptive_synth_eval.clients.chatbot import ChatbotClient
from adaptive_synth_eval.clients.chatbot_factory import create_chatbot_client
from adaptive_synth_eval.config.schemas import BrowserChatbot, TargetChatbot


def test_create_chatbot_client_defaults_to_api_client():
    config = TargetChatbot(enabled=True, endpoint="https://api.example.com/chat")

    client = create_chatbot_client(config)

    assert isinstance(client, ChatbotClient)
    assert client.endpoint == "https://api.example.com/chat"


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
