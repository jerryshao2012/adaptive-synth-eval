"""
Example: Integrating Unified Chatbot Client with GoldenQA Pipeline

This demonstrates how to replace the old RagClient/RagService pattern
with the new unified architecture.
"""

from adaptive_synth_eval.clients.unified_chatbot import (
    create_chatbot_client,
    ChatbotConfig,
    ChatbotType,
    UnifiedChatbotClient
)


# ============================================================================
# Configuration - Define your RAG endpoints
# ============================================================================

VANILLA_RAG_URL = "https://vanillarag.bmoai-ase-use2-01.appserviceenvironment.net/api/RAGResponse?code=..."
GRAPH_RAG_URL = "https://graphrag.bmoai-ase-use2-01.appserviceenvironment.net/api/RAGResponse?code=..."


# ============================================================================
# Initialize Clients Once (can be reused across multiple queries)
# ============================================================================

def initialize_rag_clients():
    """
    Create and cache RAG clients for reuse.
    In production, you might want to use dependency injection or a singleton pattern.
    """
    
    # Vanilla RAG client
    vanilla_client = create_chatbot_client(
        chatbot_type="vanilla_rag",
        endpoint=VANILLA_RAG_URL,
        timeout_seconds=3000,  # Match your original timeout
        extra_params={
            "rag_model": ["Deployment-Model-gpt-4.1"],
            "rag_temperature": 0.01,
            "source_document_reference": "true"
        }
    )
    
    # Graph RAG client
    graph_client = create_chatbot_client(
        chatbot_type="graph_rag",
        endpoint=GRAPH_RAG_URL,
        timeout_seconds=3000
    )
    
    return {
        "vanilla": vanilla_client,
        "graph": graph_client
    }


# ============================================================================
# Updated rag_query_endpoint Function
# ============================================================================

def rag_query_endpoint_new(mode: str, question: str, clients: dict, output_dir: str = None):
    """
    Updated version using unified chatbot client.
    
    Args:
        mode: "vanilla" or "graph"
        question: The query to send
        clients: Dictionary of pre-initialized clients
        output_dir: Optional logging directory
    
    Returns:
        Tuple of (response_dict, latency_ms, input_tokens, output_tokens)
    """
    import time
    from datetime import datetime
    
    start = time.time()
    
    # Select appropriate client
    if mode == "vanilla":
        client = clients["vanilla"]
        bmo_content = ["Policies and Procedures"]
    elif mode == "graph":
        client = clients["graph"]
        bmo_content = ["BMO Policy & Procedure"]
    else:
        raise ValueError(f"Unsupported mode: {mode}")
    
    # Query using unified interface
    response = client.query(question, bmo_content=bmo_content)
    
    latency = time.time() - start
    
    # Log the event (if needed)
    if output_dir:
        log_pipeline_event(
            "rag_query_endpoint_new",
            latency,
            extra_info=f"mode={mode}, question={str(question)[:40]}, success={response.success}",
            output_dir=output_dir
        )
    
    # Build response dict compatible with existing code
    response_dict = {
        "llm_response": response.bot_response,
        "latency_ms": response.latency_ms,
        "status_code": response.status_code,
        "error": response.error,
        **response.metadata  # Include type-specific metadata
    }
    
    # Token counting (optional - you can keep your existing logic)
    input_tokens = len(str(response.raw)) // 4  # Approximate
    output_tokens = len(response.bot_response) // 4
    
    return response_dict, latency, input_tokens, output_tokens


# ============================================================================
# Batch Processing Example
# ============================================================================

def batch_rag_queries(questions: list, mode: str, clients: dict, max_workers: int = 5):
    """
    Process multiple questions in parallel.
    
    Args:
        questions: List of question strings
        mode: "vanilla" or "graph"
        clients: Pre-initialized clients dictionary
        max_workers: Number of parallel workers
    
    Returns:
        List of response dictionaries
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    client = clients[mode]
    results = []
    
    def query_single(question):
        try:
            response = client.query(question)
            return {
                "question": question,
                "answer": response.bot_response,
                "success": response.success,
                "latency_ms": response.latency_ms,
                "error": response.error
            }
        except Exception as e:
            return {
                "question": question,
                "answer": "",
                "success": False,
                "latency_ms": None,
                "error": str(e)
            }
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(query_single, q): i for i, q in enumerate(questions)}
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
    
    return results


# ============================================================================
# Comparison: Old vs New Approach
# ============================================================================

def old_approach_example():
    """
    This is how you used to do it (from pipeline_functions.py).
    Notice the duplicated code and tight coupling.
    """
    from rag_client import RagClient
    from rag_service import RagService
    
    mode = "vanilla"
    question = "What is parental leave?"
    
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
    
    return raw_dict


def new_approach_example():
    """
    New approach with unified client.
    Clean, consistent, and extensible.
    """
    # Initialize once
    clients = initialize_rag_clients()
    
    # Use anywhere with simple interface
    mode = "vanilla"
    question = "What is parental leave?"
    
    response_dict, latency, _, _ = rag_query_endpoint_new(mode, question, clients)
    
    return response_dict


# ============================================================================
# Adding a New RAG Type (Future-Proof)
# ============================================================================

def example_adding_custom_rag():
    """
    Demonstrate how easy it is to add a new RAG type.
    No changes needed to existing code!
    """
    from adaptive_synth_eval.clients.unified_chatbot import (
        BaseChatbotStrategy,
        ChatbotClientFactory,
        ChatbotType
    )
    
    # Step 1: Define new strategy
    class CustomRAGStrategy(BaseChatbotStrategy):
        def build_payload(self, question: str, **kwargs):
            return {"custom_query": question}
        
        def extract_bot_response(self, raw_response):
            return raw_response.get("answer", "")
        
        def extract_metadata(self, raw_response):
            return {"custom_field": raw_response.get("custom")}
    
    # Step 2: Register it
    ChatbotClientFactory.register_strategy(
        ChatbotType("custom_rag"),
        CustomRAGStrategy
    )
    
    # Step 3: Use it immediately
    custom_client = create_chatbot_client(
        "custom_rag",
        "https://custom-rag.example.com/api"
    )
    
    response = custom_client.query("Test question")
    print(response.bot_response)


# ============================================================================
# Main Demo
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("Unified Chatbot Client - Integration Example")
    print("=" * 80)
    
    # Initialize clients
    print("\n1. Initializing RAG clients...")
    clients = initialize_rag_clients()
    print(f"   ✓ Vanilla RAG client created: {clients['vanilla'].endpoint[:50]}...")
    print(f"   ✓ Graph RAG client created: {clients['graph'].endpoint[:50]}...")
    
    # Test single query
    print("\n2. Testing single query (Vanilla RAG)...")
    question = "What is the parental leave policy?"
    response_dict, latency, _, _ = rag_query_endpoint_new("vanilla", question, clients)
    
    print(f"   Question: {question}")
    print(f"   Latency: {latency:.2f}s")
    print(f"   Success: {not response_dict.get('error')}")
    if not response_dict.get('error'):
        print(f"   Answer preview: {response_dict['llm_response'][:100]}...")
    
    # Test batch processing
    print("\n3. Testing batch processing...")
    questions = [
        "What is parental leave?",
        "How does benefits enrollment work?",
        "What are the vacation policies?"
    ]
    
    results = batch_rag_queries(questions, "vanilla", clients, max_workers=3)
    
    for i, result in enumerate(results, 1):
        status = "✓" if result["success"] else "✗"
        print(f"   {status} Q{i}: {result['question'][:40]}...")
        if result["success"]:
            print(f"      Answer: {result['answer'][:60]}...")
    
    print("\n" + "=" * 80)
    print("Demo complete!")
    print("=" * 80)
