"""
Demonstration script showing rate limiting applied to chatbot clients.
"""

from adaptive_synth_eval.clients.chatbot import ChatbotClient


def demo_chatbot_client_rate_limiting():
    """Demonstrate rate limiting in ChatbotClient."""
    print("=" * 80)
    print("Demo 1: ChatbotClient with Rate Limiting")
    print("=" * 80)

    # Create a client (disabled for demo purposes)
    client = ChatbotClient(
        endpoint="https://example.com/api",
        enabled=False,  # Disabled to avoid actual API calls
        timeout_seconds=30.0
    )

    # The _send_with_retry method is now decorated with @retry_on_rate_limit
    # This means it will automatically retry on rate limit errors with exponential backoff
    response = client.send(
        conversation_id="demo-conv-1",
        session_id="demo-session-1",
        turn_id=1,
        user_message="What is the parental leave policy?"
    )

    print(f"Response success: {response.error is None}")
    print(f"Response error: {response.error}")
    print(f"Status code: {response.status_code}")
    print()


def demo_wrap_model_function():
    """Demonstrate the wrap_model_with_rate_limiting function."""
    print("=" * 80)
    print("Demo 2: wrap_model_with_rate_limiting Function")
    print("=" * 80)
    print()
    print("The wrap_model_with_rate_limiting function from retry_utils.py provides:")
    print("  1. Reactive retries with exponential backoff")
    print("  2. Proactive rate shaping (TPM/RPM limits)")
    print()
    print("Usage example (when LangChain models are integrated):")
    print("""
    from langchain_openai import AzureChatOpenAI
    from adaptive_synth_eval.clients.retry_utils import wrap_model_with_rate_limiting
    
    # Create a LangChain model
    model = AzureChatOpenAI(
        azure_deployment="gpt-4",
        temperature=0.7
    )
    
    # Wrap it with rate limiting
    wrapped_model = wrap_model_with_rate_limiting(model)
    
    # Now all invoke/ainvoke calls have automatic retry and rate limiting
    response = wrapped_model.invoke([{"role": "user", "content": "Hello"}])
    """)
    print()


def show_configuration_options():
    """Show how to configure rate limiting via environment variables."""
    print("=" * 80)
    print("Configuration Options")
    print("=" * 80)
    print()
    print("Rate limiting can be configured via environment variables:")
    print()
    print("  MODEL_MAX_RETRIES=5          # Maximum retry attempts")
    print("  MODEL_INITIAL_BACKOFF=1.0    # Initial backoff in seconds")
    print("  MODEL_MAX_BACKOFF=60.0       # Maximum backoff in seconds")
    print("  MODEL_BACKOFF_MULTIPLIER=2.0 # Exponential backoff multiplier")
    print("  MODEL_RETRY_JITTER=true      # Add randomness to prevent thundering herd")
    print()
    print("Proactive rate limiting (for wrap_model_with_rate_limiting):")
    print()
    print("  MODEL_TPM=120000  # Tokens per minute limit")
    print("  MODEL_RPM=500     # Requests per minute limit")
    print()


if __name__ == "__main__":
    demo_chatbot_client_rate_limiting()
    demo_wrap_model_function()
    show_configuration_options()

    print("=" * 80)
    print("Summary")
    print("=" * 80)
    print()
    print("✓ Applied retry_on_rate_limit decorator to ChatbotClient._send_with_retry")
    print("✓ ChatbotClient now automatically retries on rate limit errors")
    print("✓ Configurable via environment variables or decorator parameters")
    print("✓ wrap_model_with_rate_limiting available for future LangChain integration")
    print()
