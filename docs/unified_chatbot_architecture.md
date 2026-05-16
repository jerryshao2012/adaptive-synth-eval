# Unified Chatbot Client Architecture

## Table of Contents

- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Architecture Design](#architecture-design)
  - [Key Components](#key-components)
  - [Design Patterns Used](#design-patterns-used)
  - [Architecture Diagram](#architecture-diagram)
- [Quick Start](#quick-start)
  - [Basic Usage](#basic-usage)
  - [Advanced Configuration](#advanced-configuration)
  - [Switching Between RAG Types](#switching-between-rag-types)
- [API Reference](#api-reference)
  - [Creating Clients](#creating-clients)
  - [Querying](#querying)
  - [Response Object](#response-object)
- [Migration from Old Code](#migration-from-old-code)
  - [Before (pipeline_functions.py)](#before-pipeline_functionspy)
  - [After (New Architecture)](#after-new-architecture)
  - [Migration Cheat Sheet](#migration-cheat-sheet)
- [Common Patterns](#common-patterns)
  - [Multiple Clients](#multiple-clients)
  - [Batch Processing](#batch-processing)
  - [Parallel Processing](#parallel-processing)
  - [Retry Logic](#retry-logic)
  - [Caching](#caching)
- [Supported Chatbot Types](#supported-chatbot-types)
  - [Vanilla RAG](#vanilla-rag-vanilla_rag)
  - [Graph RAG](#graph-rag-graph_rag)
- [Adding New Chatbot Types](#adding-new-chatbot-types)
  - [Step-by-Step Guide](#step-by-step-guide)
  - [Visual Guide](#visual-guide)
- [Configuration Management](#configuration-management)
  - [From Dictionary](#from-dictionary)
  - [From YAML File](#from-yaml-file)
  - [From Environment Variables](#from-environment-variables)
- [Error Handling](#error-handling)
  - [Check Success](#check-success)
  - [Handle Specific Errors](#handle-specific-errors)
  - [Try-Except Wrapper](#try-except-wrapper)
- [Testing](#testing)
  - [Mock Client for Tests](#mock-client-for-tests)
  - [Test Different Scenarios](#test-different-scenarios)
- [Performance Tips](#performance-tips)
- [Troubleshooting](#troubleshooting)
- [Benefits of This Architecture](#benefits-of-this-architecture)
- [Design Principles Applied](#design-principles-applied)
- [Future Enhancements](#future-enhancements)

---

## Overview

This document describes the new unified chatbot client architecture that supports multiple RAG types (Vanilla RAG, Graph RAG) and can be easily extended for future chatbot implementations.

## Problem Statement

Your current implementation in `pipeline_functions.py` has two RAG types (Vanilla RAG and Graph RAG) that:
1. Use the same `RagClient` class but with different URLs
2. Have duplicated initialization code
3. Require conditional logic to switch between types
4. Are difficult to extend with new chatbot types

## Solution Overview

I've designed a **Strategy Pattern + Factory Pattern** architecture that provides:

✅ **Unified Interface**: All chatbot types use the same API  
✅ **Easy Extension**: Add new types without modifying existing code  
✅ **Configuration-Driven**: Support external config files  
✅ **Type Safety**: Strong typing with dataclasses and enums  
✅ **Testability**: Each component can be tested independently

## Architecture Design

### Key Components

1. **ChatbotType Enum**: Defines supported chatbot types
2. **ChatbotConfig**: Configuration dataclass for chatbot instances
3. **BaseChatbotStrategy**: Abstract base class defining the interface
4. **Concrete Strategies**: `VanillaRAGStrategy`, `GraphRAGStrategy`
5. **ChatbotClientFactory**: Factory pattern for creating strategies
6. **UnifiedChatbotClient**: High-level facade for easy usage

### Design Patterns Used

- **Strategy Pattern**: Different RAG implementations are interchangeable strategies
- **Factory Pattern**: Creates appropriate strategy based on configuration
- **Facade Pattern**: Simplified interface through `UnifiedChatbotClient`
- **Open/Closed Principle**: Easy to add new types without modifying existing code

### Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│           UnifiedChatbotClient (Facade)              │
│  - Simple query() method for all chatbot types      │
│  - Delegates to appropriate strategy                │
└──────────────────┬──────────────────────────────────┘
                   │
                   │ Creates via Factory
                   ▼
┌─────────────────────────────────────────────────────┐
│        ChatbotClientFactory (Factory)                │
│  - Maps ChatbotType → Strategy Class                │
│  - Creates configured strategy instances            │
└──────────────────┬──────────────────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
┌──────────────┐      ┌──────────────┐
│ VanillaRAG   │      │  GraphRAG    │
│  Strategy    │      │  Strategy    │
│              │      │              │
│ build_       │      │ build_       │
│ payload()    │      │ payload()    │
│              │      │              │
│ extract_     │      │ extract_     │
│ response()   │      │ response()   │
│              │      │              │
│ extract_     │      │ extract_     │
│ metadata()   │      │ metadata()   │
└──────────────┘      └──────────────┘
       │                       │
       └───────────┬───────────┘
                   │
                   │ Implements
                   ▼
┌─────────────────────────────────────────────────────┐
│       BaseChatbotStrategy (Abstract Base)           │
│  - Defines common interface                         │
│  - Provides shared HTTP request logic               │
└─────────────────────────────────────────────────────┘
```

## Quick Start

### Basic Usage

```python
from adaptive_synth_eval.clients.unified_chatbot import (
    create_chatbot_client,
    ChatbotConfig,
    ChatbotType,
    UnifiedChatbotClient
)

# Method 1: Quick setup with convenience function
client = create_chatbot_client(
    chatbot_type="vanilla_rag",
    endpoint="https://your-rag-endpoint.com/api"
)

response = client.query("What is parental leave?")
print(response.bot_response)
print(f"Latency: {response.latency_ms}ms")
print(f"Success: {response.success}")
```

### Advanced Configuration

```python
# Method 2: Full configuration control
config = ChatbotConfig(
    chatbot_type=ChatbotType.VANILLA_RAG,
    endpoint="https://vanilla-rag.example.com/api",
    timeout_seconds=30.0,
    auth={"type": "bearer", "env_var": "API_TOKEN"},
    extra_params={
        "rag_model": ["gpt-4"],
        "rag_temperature": 0.5
    }
)

client = UnifiedChatbotClient(config)
response = client.query(
    "What is parental leave?",
    bmo_content=["Policies and Procedures"],
    rag_model=["gpt-4"],
    rag_temperature=0.5
)
```

### Switching Between RAG Types

```python
# Vanilla RAG
vanilla_client = create_chatbot_client(
    "vanilla_rag",
    "https://vanilla-rag.example.com/api"
)

# Graph RAG
graph_client = create_chatbot_client(
    "graph_rag",
    "https://graph-rag.example.com/api"
)

# Both use the same interface!
response1 = vanilla_client.query("Question 1")
response2 = graph_client.query("Question 2")
```

## API Reference

### Creating Clients

#### Method 1: Convenience Function (Recommended)
```python
client = create_chatbot_client(
    chatbot_type="vanilla_rag",  # or "graph_rag"
    endpoint="https://api.example.com",
    timeout_seconds=60.0,
    auth={"type": "bearer", "env_var": "API_TOKEN"},
    extra_params={"rag_model": ["gpt-4"]}
)
```

#### Method 2: Full Configuration
```python
config = ChatbotConfig(
    chatbot_type=ChatbotType.VANILLA_RAG,
    endpoint="https://api.example.com",
    timeout_seconds=60.0,
    auth={"type": "bearer", "env_var": "API_TOKEN"},
    extra_params={"rag_model": ["gpt-4"]}
)
client = UnifiedChatbotClient(config)
```

### Querying

#### Basic Query
```python
response = client.query("Your question here")
```

#### Query with Custom Parameters
```python
# Vanilla RAG
response = client.query(
    "Question",
    bmo_content=["Custom Content"],
    rag_model=["custom-model"],
    rag_temperature=0.5
)

# Graph RAG
response = client.query(
    "Question",
    bmo_content=["Policy"],
    session_id="custom-session",
    user_id="custom-user"
)
```

### Response Object

```python
@dataclass(frozen=True)
class ChatbotResponse:
    raw: dict[str, Any]              # Raw API response
    bot_response: str                 # Extracted text
    latency_ms: float | None         # Request latency in ms
    status_code: int                 # HTTP status code
    error: str | None                # Error message if failed
    metadata: dict[str, Any]         # Type-specific metadata
    
    @property
    def success(self) -> bool:       # True if no error and status 200
        return self.error is None and self.status_code == 200
```

#### Accessing Response Data
```python
response = client.query("Question")

# Check success
if response.success:
    print(f"Answer: {response.bot_response}")
    print(f"Latency: {response.latency_ms:.2f}ms")
else:
    print(f"Error: {response.error}")

# Access type-specific metadata
if client.chatbot_type == ChatbotType.VANILLA_RAG:
    retrieved = response.metadata.get("retrieved_content")
    
elif client.chatbot_type == ChatbotType.GRAPH_RAG:
    graph_data = response.metadata.get("graph")
    references = response.metadata.get("references")
```

## Migration from Old Code

### Before (pipeline_functions.py)

```python
def rag_query_endpoint(mode: str, question: str, output_dir: str = None):
    if mode == "vanilla":
        url = VANILLA_RAG_URL
        bmo_content_list = ["Policies and Procedures"]
        rag_client_instance = RagClient(url=url)
        rag_service = RagService(
            rag_client=rag_client_instance,
            rag_model=["Deployment-Model-gpt-4.1"],
            rag_temperature=0.01,
            source_document_reference="true"
        )
        raw_dict, input_tokens, output_tokens = rag_service.call_vanilla(question, bmo_content_list)
    elif mode == "graph":
        url = GRAPH_RAG_URL
        bmo_content_list = ["BMO Policy & Procedure"]
        rag_client_instance = RagClient(url=url)
        rag_service = RagService(...)
        raw_dict, input_tokens, output_tokens = rag_service.call_graph_rag(question, bmo_content_list)
    
    return raw_dict, latency, input_tokens, output_tokens
```

### After (New Architecture)

```python
from adaptive_synth_eval.clients.unified_chatbot import create_chatbot_client

# Initialize clients once (can be cached/reused)
VANILLA_CLIENT = create_chatbot_client(
    "vanilla_rag",
    VANILLA_RAG_URL,
    extra_params={
        "rag_model": ["Deployment-Model-gpt-4.1"],
        "rag_temperature": 0.01
    }
)

GRAPH_CLIENT = create_chatbot_client(
    "graph_rag",
    GRAPH_RAG_URL
)

def rag_query_endpoint(mode: str, question: str, output_dir: str = None):
    # Select client based on mode
    client = VANILLA_CLIENT if mode == "vanilla" else GRAPH_CLIENT
    
    # Query using unified interface
    response = client.query(question)
    
    # Access standardized response
    return {
        "raw": response.raw,
        "llm_response": response.bot_response,
        "latency_ms": response.latency_ms,
        "status_code": response.status_code,
        "error": response.error,
        **response.metadata
    }, response.latency_ms, None, None
```

### Migration Cheat Sheet

| Old | New |
|-----|-----|
| `RagClient(url)` | `create_chatbot_client(type, url)` |
| `RagService.call_vanilla(q, content)` | `client.query(q, bmo_content=content)` |
| `RagService.call_graph_rag(q, content)` | `client.query(q, bmo_content=content)` |
| `raw_dict["llm_response"]` | `response.bot_response` |
| Manual latency tracking | `response.latency_ms` |
| Manual error checking | `response.error`, `response.success` |

### Step 2: Benefits You Get Immediately

1. **Cleaner Code**: No duplicated RagClient/RagService initialization
2. **Consistent Interface**: Same `.query()` method for all types
3. **Better Error Handling**: Standardized error responses
4. **Easier Testing**: Mock one interface instead of multiple classes
5. **Future-Proof**: Easy to add Azure OpenAI, custom APIs, etc.

## Common Patterns

### Pattern 1: Multiple Clients
```python
# Initialize different clients
vanilla = create_chatbot_client("vanilla_rag", VANILLA_URL)
graph = create_chatbot_client("graph_rag", GRAPH_URL)

# Use based on condition
def answer_question(question, use_graph=False):
    client = graph if use_graph else vanilla
    return client.query(question)
```

### Pattern 2: Batch Processing
```python
questions = ["Q1", "Q2", "Q3"]
responses = [client.query(q) for q in questions]

# Process results
for q, r in zip(questions, responses):
    if r.success:
        print(f"Q: {q}")
        print(f"A: {r.bot_response}\n")
```

### Pattern 3: Parallel Processing
```python
from concurrent.futures import ThreadPoolExecutor

def batch_query_parallel(client, questions, max_workers=5):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(client.query, q) for q in questions]
        return [f.result() for f in futures]

responses = batch_query_parallel(client, questions, max_workers=10)
```

### Pattern 4: Retry Logic
```python
import time

def query_with_retry(client, question, max_retries=3, backoff=1.0):
    for attempt in range(max_retries):
        response = client.query(question)
        if response.success:
            return response
        
        print(f"Attempt {attempt + 1} failed: {response.error}")
        time.sleep(backoff * (2 ** attempt))  # Exponential backoff
    
    return response  # Return last failed response
```

### Pattern 5: Caching
```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_query(client_key, question):
    """Cache queries by client key and question."""
    client = get_client(client_key)  # Your client factory
    return client.query(question)
```

## Supported Chatbot Types

### Vanilla RAG (`vanilla_rag`)
**Endpoint**: Standard RAG API  
**Request Format**:
```json
{
  "query": "question",
  "bmo_content": ["Policies and Procedures"],
  "butler_11m_config": {
    "rag_model": ["Deployment-Model-gpt-4.1"],
    "rag_temperature": 0.01,
    "source_document_reference": "true"
  }
}
```

**Response Metadata**:
- `retrieved_content`: Retrieved documents
- `used_bmo_content`: Used BMO content list

### Graph RAG (`graph_rag`)
**Endpoint**: Graph-enhanced RAG API  
**Request Format**:
```json
{
  "query": "question",
  "bmo_content": ["BMO Policy & Procedure"],
  "session_id": "uuid",
  "user_id": "user_xxx"
}
```

**Response Metadata**:
- `graph`: Graph data structure
- `references`: Reference list
- `retrieved_content`: Retrieved content
- `used_bmo_content`: Used BMO content

## Adding New Chatbot Types

To add a new chatbot type (e.g., Azure OpenAI), follow these steps:

### Step-by-Step Guide

### Step 1: Define the Type

```python
# In unified_chatbot.py
class ChatbotType(str, Enum):
    VANILLA_RAG = "vanilla_rag"
    GRAPH_RAG = "graph_rag"
    AZURE_OPENAI = "azure_openai"  # Add new type
```

### Step 2: Create Strategy Class

```python
class AzureOpenAIStrategy(BaseChatbotStrategy):
    def build_payload(self, question: str, **kwargs) -> dict[str, Any]:
        return {
            "messages": [
                {"role": "user", "content": question}
            ],
            "model": kwargs.get("model", "gpt-4"),
            "temperature": kwargs.get("temperature", 0.7)
        }
    
    def extract_bot_response(self, raw_response: dict[str, Any]) -> str:
        return raw_response.get("choices", [{}])[0].get("message", {}).get("content", "")
    
    def extract_metadata(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        return {
            "usage": raw_response.get("usage", {}),
            "model": raw_response.get("model", "")
        }
```

### Step 3: Register in Factory

```python
# In ChatbotClientFactory
_strategies = {
    ChatbotType.VANILLA_RAG: VanillaRAGStrategy,
    ChatbotType.GRAPH_RAG: GraphRAGStrategy,
    ChatbotType.AZURE_OPENAI: AzureOpenAIStrategy,  # Add mapping
}
```

That's it! The new type is now available:

```python
azure_client = create_chatbot_client(
    "azure_openai",
    "https://your-openai-endpoint.openai.azure.com/",
    auth={"type": "bearer", "env_var": "AZURE_OPENAI_KEY"}
)
```

**No changes needed to existing code!** 🎉

### Visual Guide

```
Step 1: Add enum value
┌──────────────────────────────┐
│ class ChatbotType(Enum):     │
│   VANILLA_RAG = "vanilla"    │
│   GRAPH_RAG = "graph"        │
│   AZURE_OPENAI = "azure"  ←──┼── Add this
└──────────────────────────────┘

Step 2: Create strategy
┌──────────────────────────────┐
│ class AzureOpenAIStrategy(   │
│   BaseChatbotStrategy        │
│ ):                           │
│                              │
│   def build_payload(...):    │
│     return {                 │
│       "messages": [...],     │
│       "model": "gpt-4"       │
│     }                        │
│                              │
│   def extract_response(...): │
│     return raw["choices"][0] │
│                              │
│   def extract_metadata(...): │
│     return {"usage": ...}    │
└──────────────────────────────┘

Step 3: Register in factory
┌──────────────────────────────┐
│ ChatbotClientFactory.        │
│   _strategies[               │
│     AZURE_OPENAI             │
│   ] = AzureOpenAIStrategy    │
└──────────────────────────────┘

Step 4: Use it!
┌──────────────────────────────┐
│ azure_client =               │
│   create_chatbot_client(     │
│     "azure_openai",          │
│     AZURE_ENDPOINT           │
│   )                          │
│                              │
│ response =                   │
│   azure_client.query(        │
│     "Question"               │
│   )                          │
└──────────────────────────────┘

✅ No changes to existing code!
✅ No changes to Vanilla/Graph strategies!
✅ Works immediately!
```

## Response Handling

All chatbot responses follow the same structure:

```python
@dataclass(frozen=True)
class ChatbotResponse:
    raw: dict[str, Any]              # Raw API response
    bot_response: str                 # Extracted text response
    latency_ms: float | None         # Request latency
    status_code: int                 # HTTP status code
    error: str | None                # Error message if failed
    metadata: dict[str, Any]         # Type-specific metadata
    
    @property
    def success(self) -> bool:       # Convenience property
        return self.error is None and self.status_code == 200
```

### Example Response Handling

```python
response = client.query("Your question here")

if response.success:
    print(f"Answer: {response.bot_response}")
    print(f"Latency: {response.latency_ms:.2f}ms")
    
    # Access type-specific metadata
    if client.chatbot_type == ChatbotType.GRAPH_RAG:
        print(f"Graph data: {response.metadata.get('graph')}")
        print(f"References: {response.metadata.get('references')}")
else:
    print(f"Error: {response.error}")
    print(f"Status: {response.status_code}")
```

## Batch Processing

```python
from concurrent.futures import ThreadPoolExecutor

def batch_query(client, questions, max_workers=5):
    """Query multiple questions in parallel."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(client.query, q): i 
                   for i, q in enumerate(questions)}
        
        results = [None] * len(questions)
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = ChatbotResponse(
                    raw={},
                    bot_response="",
                    latency_ms=None,
                    status_code=0,
                    error=str(e)
                )
    
    return results

# Usage
questions = ["Q1", "Q2", "Q3", ...]
responses = batch_query(vanilla_client, questions)
```

## Configuration Management

Store configurations in YAML or JSON files:

### From Dictionary
```python
config_dict = {
    "chatbot_type": "vanilla_rag",
    "endpoint": "https://api.example.com",
    "timeout_seconds": 30,
    "auth": {"type": "bearer", "env_var": "API_KEY"},
    "extra_params": {"rag_model": ["gpt-4"]}
}

config = ChatbotConfig.from_dict(config_dict)
client = UnifiedChatbotClient(config)
```

### From YAML File
```yaml
# config.yaml
vanilla_rag:
  chatbot_type: vanilla_rag
  endpoint: https://vanilla.api.com
  timeout_seconds: 30
  
graph_rag:
  chatbot_type: graph_rag
  endpoint: https://graph.api.com
  timeout_seconds: 60
```

```python
import yaml

with open("config.yaml") as f:
    configs = yaml.safe_load(f)

vanilla_config = ChatbotConfig.from_dict(configs["vanilla_rag"])
vanilla_client = UnifiedChatbotClient(vanilla_config)
```

### From Environment Variables
```python
import os

client = create_chatbot_client(
    chatbot_type=os.getenv("CHATBOT_TYPE", "vanilla_rag"),
    endpoint=os.getenv("CHATBOT_ENDPOINT"),
    timeout_seconds=float(os.getenv("CHATBOT_TIMEOUT", "60")),
    auth={
        "type": "bearer",
        "env_var": "CHATBOT_API_KEY"
    }
)
```

## Error Handling

### Check Success
```python
response = client.query("Question")

if not response.success:
    print(f"Failed: {response.error}")
    print(f"Status: {response.status_code}")
```

### Handle Specific Errors
```python
response = client.query("Question")

if response.error:
    if "timeout" in response.error.lower():
        # Handle timeout
        retry_with_longer_timeout()
    elif "connection" in response.error.lower():
        # Handle connection error
        check_network()
    else:
        # Handle other errors
        log_error(response.error)
```

### Try-Except Wrapper
```python
try:
    response = client.query("Question")
    if response.success:
        process(response.bot_response)
    else:
        handle_error(response.error)
except Exception as e:
    handle_exception(e)
```

## Testing

The architecture includes comprehensive tests in `tests/unit/test_unified_chatbot.py`:

```bash
uv run pytest tests/unit/test_unified_chatbot.py -v
```

Tests cover:
- ✅ Strategy creation and configuration
- ✅ Payload building for each type
- ✅ Response extraction
- ✅ Error handling
- ✅ Factory pattern
- ✅ Integration scenarios
- ✅ Batch processing

### Mock Client for Tests
```python
from unittest.mock import Mock

def test_with_mock_client():
    mock_response = Mock()
    mock_response.bot_response = "Mocked answer"
    mock_response.success = True
    mock_response.latency_ms = 100.0
    
    mock_client = Mock()
    mock_client.query.return_value = mock_response
    
    # Use mock_client in your tests
    result = mock_client.query("Test")
    assert result.bot_response == "Mocked answer"
```

### Test Different Scenarios
```python
def test_success_and_failure():
    # Success case
    success_response = ChatbotResponse(
        raw={},
        bot_response="Answer",
        latency_ms=100.0,
        status_code=200
    )
    assert success_response.success is True
    
    # Failure case
    failure_response = ChatbotResponse(
        raw={},
        bot_response="",
        latency_ms=0.0,
        status_code=500,
        error="Server error"
    )
    assert failure_response.success is False
```

## Performance Tips

1. **Reuse Clients**: Create once, use many times
   ```python
   # Good
   client = create_chatbot_client(...)
   for q in questions:
       client.query(q)
   
   # Bad
   for q in questions:
       client = create_chatbot_client(...)  # Don't recreate!
       client.query(q)
   ```

2. **Adjust Timeout**: Set appropriate timeout for your use case
   ```python
   client = create_chatbot_client(..., timeout_seconds=30.0)
   ```

3. **Parallel Queries**: Use ThreadPoolExecutor for batch processing
   ```python
   with ThreadPoolExecutor(max_workers=10) as executor:
       responses = list(executor.map(client.query, questions))
   ```

4. **Monitor Latency**: Track response times
   ```python
   response = client.query(question)
   print(f"Query took {response.latency_ms:.2f}ms")
   ```

## Troubleshooting

### Issue: Connection Timeout
```python
# Solution: Increase timeout
client = create_chatbot_client(..., timeout_seconds=120.0)
```

### Issue: Authentication Error
```python
# Solution: Check auth configuration
client = create_chatbot_client(
    ...,
    auth={"type": "bearer", "env_var": "YOUR_API_KEY_VAR"}
)
# Ensure environment variable is set
```

### Issue: Empty Response
```python
# Solution: Check response.error and response.status_code
response = client.query(question)
if not response.success:
    print(f"Error: {response.error}, Status: {response.status_code}")
```

### Issue: Wrong Payload Format
```python
# Solution: Pass custom parameters
response = client.query(
    question,
    bmo_content=["Custom"],
    rag_model=["custom-model"]
)
```

## Benefits of This Architecture

1. **Extensibility**: Add new chatbot types without modifying existing code
2. **Consistency**: All chatbots use the same interface
3. **Testability**: Each strategy can be tested independently
4. **Maintainability**: Clear separation of concerns
5. **Flexibility**: Easy to switch between chatbot types at runtime
6. **Type Safety**: Strong typing with dataclasses and enums
7. **Configuration-Driven**: Support for external configuration files

## Design Principles Applied

1. **Open/Closed Principle**: Open for extension, closed for modification
2. **Single Responsibility**: Each strategy handles one protocol
3. **Dependency Inversion**: High-level code depends on abstractions
4. **Interface Segregation**: Clean, focused interfaces
5. **DRY (Don't Repeat Yourself)**: Common logic in base class

## Future Enhancements

Potential improvements:
- Async support with `aiohttp`
- Retry logic with exponential backoff
- Circuit breaker pattern for resilience
- Metrics/telemetry integration
- Response caching
- Rate limiting
- Load balancing across multiple endpoints

---

## Getting Help

1. **Review Examples**: See `examples/unified_chatbot_integration.py`
2. **Run Tests**: `uv run pytest tests/unit/test_unified_chatbot.py -v`
3. **Read Source**: `src/adaptive_synth_eval/clients/unified_chatbot.py`

## Next Steps

1. **Review** the architecture and provide feedback
2. **Test** with your actual RAG endpoints
3. **Migrate** `pipeline_functions.py` to use the new architecture
4. **Extend** by adding any additional chatbot types you need
5. **Document** any custom requirements or edge cases

---

**Remember**: This architecture is designed to make your life easier. If something feels complicated, there's probably a simpler way to do it. Don't hesitate to adapt it to your needs!
