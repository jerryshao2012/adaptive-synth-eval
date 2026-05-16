# Rate Limiting Integration Guide

## Overview

The `wrap_model_with_rate_limiting` function and related retry utilities from [retry_utils.py](../src/adaptive_synth_eval/clients/retry_utils.py) have been successfully integrated into the adaptive-synth-eval project's chatbot clients.

Both `ChatbotClient` and `UnifiedChatbotClient` now automatically retry failed requests due to rate limiting, making the system more resilient to transient API errors while maintaining full backward compatibility.

## What Was Applied

### Changes Made

#### 1. Modified Files

##### [chatbot.py](../src/adaptive_synth_eval/clients/chatbot.py)
- **Added import**: `from adaptive_synth_eval.clients.retry_utils import retry_on_rate_limit`
- **Refactored `send()` method**: Split into public `send()` and internal `_send_with_retry()` 
- **Applied decorator**: `@retry_on_rate_limit(max_retries=3, initial_backoff=1.0, max_backoff=30.0)` to `_send_with_retry()`
- **Result**: All HTTP requests now automatically retry on rate limit errors

##### [unified_chatbot.py](../src/adaptive_synth_eval/clients/unified_chatbot.py)
- **Added import**: `from adaptive_synth_eval.clients.retry_utils import retry_on_rate_limit`
- **Added method**: `_send_request_with_retry()` in `BaseChatbotStrategy`
- **Applied decorator**: `@retry_on_rate_limit(max_retries=3, initial_backoff=1.0, max_backoff=30.0)` to `_send_request_with_retry()`
- **Modified `query()` method**: Now calls `_send_request_with_retry()` instead of `send_request()`
- **Result**: All strategy classes (VanillaRAG, GraphRAG, etc.) inherit rate limiting

### 1. ChatbotClient ([chatbot.py](../src/adaptive_synth_eval/clients/chatbot.py))

The `ChatbotClient.send()` method now uses the `@retry_on_rate_limit` decorator through an internal `_send_with_retry()` method:

```python
class ChatbotClient:
    def send(self, *, conversation_id: str, session_id: str, turn_id: int, user_message: str, ...) -> ChatbotResponse:
        # Public method delegates to retry-enabled internal method
        return self._send_with_retry(...)
    
    @retry_on_rate_limit(max_retries=3, initial_backoff=1.0, max_backoff=30.0)
    def _send_with_retry(self, *, conversation_id: str, session_id: str, turn_id: int, user_message: str, ...) -> ChatbotResponse:
        # Actual HTTP request with automatic retry on rate limits
        ...
```

**Benefits:**
- Automatic retry on 429/rate limit errors
- Exponential backoff (1s → 2s → 4s → 8s → 16s, max 30s)
- Up to 3 retry attempts before failing
- Jitter to prevent thundering herd problem

### 2. UnifiedChatbotClient ([unified_chatbot.py](../src/adaptive_synth_eval/clients/unified_chatbot.py))

All strategy classes (VanillaRAGStrategy, GraphRAGStrategy, etc.) now use rate-limited requests:

```python
class BaseChatbotStrategy:
    def query(self, question: str, **kwargs) -> ChatbotResponse:
        # Delegates to retry-enabled internal method
        raw_response, latency_ms, status_code, error = self._send_request_with_retry(payload)
        ...
    
    @retry_on_rate_limit(max_retries=3, initial_backoff=1.0, max_backoff=30.0)
    def _send_request_with_retry(self, payload: dict) -> tuple:
        # Wraps send_request with retry logic
        return self.send_request(payload)
```

**Benefits:**
- Consistent rate limiting across all chatbot types
- Easy to configure per-strategy if needed
- Transparent to calling code

### 3. wrap_model_with_rate_limiting Function

The original `wrap_model_with_rate_limiting()` function remains available for future LangChain model integration:

```python
from adaptive_synth_eval.clients.retry_utils import wrap_model_with_rate_limiting

# When LangChain models are added:
model = AzureChatOpenAI(azure_deployment="gpt-4")
wrapped_model = wrap_model_with_rate_limiting(model)

# Now has both:
# 1. Reactive retries (on 429 errors)
# 2. Proactive rate shaping (TPM/RPM limits)
response = wrapped_model.invoke(messages)
```

## Configuration

### Environment Variables

Rate limiting behavior can be configured via environment variables:

```bash
# Retry configuration
export MODEL_MAX_RETRIES=5              # Default: 5
export MODEL_INITIAL_BACKOFF=1.0        # Default: 1.0 seconds
export MODEL_MAX_BACKOFF=60.0           # Default: 60.0 seconds
export MODEL_BACKOFF_MULTIPLIER=2.0     # Default: 2.0
export MODEL_RETRY_JITTER=true          # Default: true

# Proactive rate limiting (for wrap_model_with_rate_limiting)
export MODEL_TPM=120000                 # Tokens per minute
export MODEL_RPM=500                    # Requests per minute
```

### Decorator Parameters

You can also configure retry behavior directly in the decorator:

```python
@retry_on_rate_limit(
    max_retries=5,
    initial_backoff=2.0,
    max_backoff=120.0,
    backoff_multiplier=2.5,
    jitter=True
)
def my_api_call():
    ...
```

## How It Works

### Retry Flow

```
Request → 429 Error → Wait (1-2s) → Retry → 429 Error → Wait (2-4s) → Retry → ...
         ↓                                                        ↓
      Success                                                  Max retries reached
                                                                  → Return error
```

### Error Detection

The system automatically detects rate limit errors by checking for these indicators:
- ✅ "rate limit" / "rate_limit" / "ratelimit"
- ✅ "too many requests"
- ✅ "429" (HTTP status code)
- ✅ "throttl"
- ✅ "quota exceeded"
- ✅ "usage limit"
- ✅ "request limit"
- ✅ "calls per minute" / "tokens per minute" / "requests per minute"
- ❌ Content filter errors (NOT retried - they're intentional rejections)

### Retry Strategy

1. **First attempt**: Immediate execution
2. **Retry 1**: Wait 1-2 seconds (with jitter)
3. **Retry 2**: Wait 2-4 seconds (with jitter)
4. **Retry 3**: Wait 4-8 seconds (with jitter)
5. **Max reached**: Raise exception with last error

### Backoff Schedule

With default settings (initial=1.0, multiplier=2.0, max=30.0):

| Attempt | Wait Time (no jitter) | Wait Time (with jitter) |
|---------|----------------------|------------------------|
| 1       | 1.0s                 | 0.5-1.0s               |
| 2       | 2.0s                 | 1.0-2.0s               |
| 3       | 4.0s                 | 2.0-4.0s               |
| 4       | 8.0s                 | 4.0-8.0s               |
| 5+      | 30.0s (capped)       | 15.0-30.0s             |

### Backoff Calculation

```python
backoff = min(initial_backoff * (multiplier ^ attempt), max_backoff)
if jitter:
    backoff = backoff * (0.5 + random.random() * 0.5)  # 50-100% of calculated backoff
```

## Usage Examples

### Example 1: Basic ChatbotClient Usage

```python
from adaptive_synth_eval.clients.chatbot import ChatbotClient

client = ChatbotClient(
    endpoint="https://your-chatbot-api.com/api",
    enabled=True,
    auth={"type": "bearer", "env_var": "CHATBOT_API_KEY"},
    timeout_seconds=60.0
)

# This call will automatically retry on rate limit errors
response = client.send(
    conversation_id="conv-123",
    session_id="session-456",
    turn_id=1,
    user_message="What is the parental leave policy?"
)

if response.success:
    print(f"Bot response: {response.bot_response}")
else:
    print(f"Error after retries: {response.error}")
```

### Example 2: UnifiedChatbotClient Usage

```python
from adaptive_synth_eval.clients.unified_chatbot import create_chatbot_client

# Create client for Vanilla RAG
vanilla_client = create_chatbot_client(
    chatbot_type="vanilla_rag",
    endpoint="https://vanilla-rag-api.com/api",
    timeout_seconds=30.0
)

# Create client for Graph RAG
graph_client = create_chatbot_client(
    chatbot_type="graph_rag",
    endpoint="https://graph-rag-api.com/api",
    timeout_seconds=30.0
)

# Both clients have automatic rate limiting
response1 = vanilla_client.query("What benefits am I eligible for?")
response2 = graph_client.query("How do I enroll in health insurance?")
```

### Example 3: Future LangChain Integration

```python
from langchain_openai import AzureChatOpenAI
from adaptive_synth_eval.clients.retry_utils import wrap_model_with_rate_limiting

# Create LangChain model
model = AzureChatOpenAI(
    azure_endpoint="https://your-resource.openai.azure.com/",
    azure_deployment="gpt-4",
    api_version="2024-02-15-preview",
    temperature=0.7
)

# Wrap with rate limiting
wrapped_model = wrap_model_with_rate_limiting(model)

# Use as normal - rate limiting is transparent
from langchain_core.messages import HumanMessage

response = wrapped_model.invoke([
    HumanMessage(content="Generate a summary of HR policies")
])

print(response.content)
```

## Testing

### Quick Test

Run the demo script to see rate limiting in action:

```bash
uv run python examples/demo_rate_limiting.py
```

### Verify No Regressions

Run existing tests to ensure no regressions:

```bash
uv run pytest tests/unit/test_chatbot_client.py -v
uv run pytest tests/unit/test_unified_chatbot.py -v
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                  Application Layer                   │
│                                                       │
│  ChatbotClient.send()                                │
│  UnifiedChatbotClient.query()                        │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│            Rate Limiting Layer                       │
│                                                       │
│  @retry_on_rate_limit decorator                      │
│  - Detects 429/rate limit errors                     │
│  - Exponential backoff with jitter                   │
│  - Configurable retries (default: 3)                 │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│              HTTP Request Layer                      │
│                                                       │
│  requests.post(endpoint, json=payload, ...)          │
│  - Authentication                                    │
│  - Timeout handling                                  │
│  - Response parsing                                  │
└─────────────────────────────────────────────────────┘
```

## Benefits

1. ✅ **Resilience**: Automatically handles transient rate limit errors
2. ✅ **Configurability**: Tune retry behavior via environment variables or parameters
3. ✅ **Zero Breaking Changes**: Fully backward compatible - no code changes needed!
4. ✅ **Consistency**: Same retry logic across all chatbot clients
5. ✅ **Future-Proof**: `wrap_model_with_rate_limiting` ready for LangChain integration
6. ✅ **Observability**: Logs retry attempts for debugging
7. ✅ **Best Practices**: Exponential backoff with jitter prevents thundering herd problem

## Migration Notes

### For Existing Code

No changes required! The rate limiting is applied transparently:

#### Before (No Rate Limiting)
```python
client = ChatbotClient(endpoint="https://api.example.com")
response = client.send(...)  # Fails immediately on 429
```

#### After (Automatic Rate Limiting)
```python
client = ChatbotClient(endpoint="https://api.example.com")
response = client.send(...)  # Retries up to 3 times on 429
```

**No code changes required!**

### For New Integrations

When adding new chatbot strategies or clients, simply apply the decorator:

```python
@retry_on_rate_limit(max_retries=3, initial_backoff=1.0, max_backoff=30.0)
def your_api_method(...):
    # Your HTTP request logic here
    pass
```

## Troubleshooting

### Issue: Too many retries causing delays

**Solution:** Reduce `max_retries` or `max_backoff`:

```python
@retry_on_rate_limit(max_retries=2, max_backoff=10.0)
def fast_failing_call():
    ...
```

### Issue: Not retrying when expected

**Solution:** Check that the error message contains rate limit indicators. Add custom detection if needed:

```python
from adaptive_synth_eval.clients.retry_utils import is_rate_limit_error

# Extend detection logic
def custom_is_rate_limit(error: Exception) -> bool:
    if is_rate_limit_error(error):
        return True
    # Add custom checks
    return "custom-rate-limit-indicator" in str(error).lower()
```

### Issue: Want different retry config per endpoint

**Solution:** Use different decorator parameters:

```python
class MyStrategy(BaseChatbotStrategy):
    @retry_on_rate_limit(max_retries=5, max_backoff=60.0)  # More aggressive for critical endpoint
    def _send_critical_request(self, payload):
        ...
    
    @retry_on_rate_limit(max_retries=1, max_backoff=5.0)   # Less aggressive for non-critical
    def _send_non_critical_request(self, payload):
        ...
```

## Related Files

- [retry_utils.py](../src/adaptive_synth_eval/clients/retry_utils.py) - Core retry utilities
- [chatbot.py](../src/adaptive_synth_eval/clients/chatbot.py) - ChatbotClient with rate limiting
- [unified_chatbot.py](../src/adaptive_synth_eval/clients/unified_chatbot.py) - UnifiedChatbotClient with rate limiting
- [demo_rate_limiting.py](../examples/demo_rate_limiting.py) - Demonstration script

## Summary & Verification Checklist

### What Was Done

✅ Applied `retry_on_rate_limit` decorator to `ChatbotClient._send_with_retry`  
✅ Applied `retry_on_rate_limit` decorator to `BaseChatbotStrategy._send_request_with_retry`  
✅ Both clients now automatically retry on rate limit errors  
✅ Configurable via environment variables or decorator parameters  
✅ `wrap_model_with_rate_limiting` available for future LangChain integration  
✅ Zero breaking changes - fully backward compatible  

### Verification Checklist

- ✅ Import statements added correctly
- ✅ Decorator applied to appropriate methods
- ✅ No syntax errors
- ✅ Backward compatibility maintained
- ✅ Documentation created
- ✅ Demo script created
- ✅ Configuration options documented

### Next Steps

1. **Test with real API**: Run against actual chatbot endpoints to verify retry behavior
2. **Monitor logs**: Check that retry attempts are logged correctly
3. **Tune configuration**: Adjust retry parameters based on observed API behavior
4. **Consider proactive limiting**: Enable TPM/RPM limits if experiencing frequent 429s

### Future Enhancements

The `wrap_model_with_rate_limiting()` function is ready for LangChain integration:

```python
from langchain_openai import AzureChatOpenAI
from adaptive_synth_eval.clients.retry_utils import wrap_model_with_rate_limiting

model = AzureChatOpenAI(azure_deployment="gpt-4")
wrapped_model = wrap_model_with_rate_limiting(model)

# Now has both reactive retries AND proactive rate shaping
response = wrapped_model.invoke(messages)
```

This provides:
1. **Reactive retries**: Handle 429 errors after they occur
2. **Proactive rate shaping**: Prevent 429 errors by controlling request flow (TPM/RPM limits)  
