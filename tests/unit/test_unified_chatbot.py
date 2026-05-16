"""Tests for unified chatbot client architecture."""

from unittest.mock import Mock, patch

import pytest

from adaptive_synth_eval.clients.unified_chatbot import (
    ChatbotType,
    ChatbotConfig,
    ChatbotResponse,
    VanillaRAGStrategy,
    GraphRAGStrategy,
    ChatbotClientFactory,
    UnifiedChatbotClient,
    create_chatbot_client,
)


class TestChatbotResponse:
    """Test ChatbotResponse dataclass."""

    def test_successful_response(self):
        response = ChatbotResponse(
            raw={"llm_response": "test answer"},
            bot_response="test answer",
            latency_ms=123.45,
            status_code=200
        )

        assert response.success is True
        assert response.bot_response == "test answer"
        assert response.latency_ms == 123.45

    def test_failed_response_with_error(self):
        response = ChatbotResponse(
            raw={},
            bot_response="",
            latency_ms=0.0,
            status_code=500,
            error="Server error"
        )

        assert response.success is False
        assert response.error == "Server error"

    def test_metadata_storage(self):
        metadata = {"retrieved_content": {"doc1": "content"}}
        response = ChatbotResponse(
            raw={},
            bot_response="answer",
            latency_ms=100.0,
            status_code=200,
            metadata=metadata
        )

        assert response.metadata == metadata


class TestChatbotConfig:
    """Test ChatbotConfig creation and validation."""

    def test_create_from_dict_vanilla_rag(self):
        config_dict = {
            "chatbot_type": "vanilla_rag",
            "endpoint": "https://example.com/api",
            "timeout_seconds": 30.0,
            "extra_params": {"rag_model": ["gpt-4"]}
        }

        config = ChatbotConfig.from_dict(config_dict)

        assert config.chatbot_type == ChatbotType.VANILLA_RAG
        assert config.endpoint == "https://example.com/api"
        assert config.timeout_seconds == 30.0
        assert config.extra_params == {"rag_model": ["gpt-4"]}

    def test_create_from_dict_graph_rag(self):
        config_dict = {
            "chatbot_type": "graph_rag",
            "endpoint": "https://graph.example.com/api"
        }

        config = ChatbotConfig.from_dict(config_dict)

        assert config.chatbot_type == ChatbotType.GRAPH_RAG
        assert config.endpoint == "https://graph.example.com/api"
        assert config.timeout_seconds == 60.0  # default

    def test_invalid_chatbot_type(self):
        config_dict = {
            "chatbot_type": "invalid_type",
            "endpoint": "https://example.com"
        }

        with pytest.raises(ValueError):
            ChatbotConfig.from_dict(config_dict)


class TestVanillaRAGStrategy:
    """Test Vanilla RAG strategy implementation."""

    @pytest.fixture
    def config(self):
        return ChatbotConfig(
            chatbot_type=ChatbotType.VANILLA_RAG,
            endpoint="https://vanilla-rag.example.com/api"
        )

    @pytest.fixture
    def strategy(self, config):
        return VanillaRAGStrategy(config)

    def test_build_payload_default(self, strategy):
        payload = strategy.build_payload("What is parental leave?")

        assert payload["query"] == "What is parental leave?"
        assert payload["bmo_content"] == ["Policies and Procedures"]
        assert "butler_11m_config" in payload
        assert payload["butler_11m_config"]["rag_model"] == ["Deployment-Model-gpt-4.1"]
        assert payload["butler_11m_config"]["rag_temperature"] == 0.01

    def test_build_payload_custom(self, strategy):
        payload = strategy.build_payload(
            "Test question",
            bmo_content=["Custom Content"],
            rag_model=["custom-model"],
            rag_temperature=0.5
        )

        assert payload["bmo_content"] == ["Custom Content"]
        assert payload["butler_11m_config"]["rag_model"] == ["custom-model"]
        assert payload["butler_11m_config"]["rag_temperature"] == 0.5

    def test_extract_bot_response(self, strategy):
        raw = {"llm_response": "This is the answer"}
        response = strategy.extract_bot_response(raw)

        assert response == "This is the answer"

    def test_extract_bot_response_empty(self, strategy):
        raw = {"llm_response": ""}
        response = strategy.extract_bot_response(raw)

        assert response == ""

    def test_extract_metadata(self, strategy):
        raw = {
            "retrieved_content": {"doc": "content"},
            "used_bmo_content": ["Policy A"]
        }
        metadata = strategy.extract_metadata(raw)

        assert metadata["retrieved_content"] == {"doc": "content"}
        assert metadata["used_bmo_content"] == ["Policy A"]


class TestGraphRAGStrategy:
    """Test Graph RAG strategy implementation."""

    @pytest.fixture
    def config(self):
        return ChatbotConfig(
            chatbot_type=ChatbotType.GRAPH_RAG,
            endpoint="https://graph-rag.example.com/api"
        )

    @pytest.fixture
    def strategy(self, config):
        return GraphRAGStrategy(config)

    def test_build_payload_default(self, strategy):
        payload = strategy.build_payload("What is the policy?")

        assert payload["query"] == "What is the policy?"
        assert payload["bmo_content"] == ["BMO Policy & Procedure"]
        assert "session_id" in payload
        assert "user_id" in payload

    def test_build_payload_custom(self, strategy):
        payload = strategy.build_payload(
            "Test",
            bmo_content=["Custom"],
            session_id="custom-session",
            user_id="custom-user"
        )

        assert payload["bmo_content"] == ["Custom"]
        assert payload["session_id"] == "custom-session"
        assert payload["user_id"] == "custom-user"

    def test_extract_bot_response(self, strategy):
        raw = {"llm_response": "Graph-based answer"}
        response = strategy.extract_bot_response(raw)

        assert response == "Graph-based answer"

    def test_extract_metadata(self, strategy):
        raw = {
            "graph": "graph_data",
            "references": ["ref1", "ref2"],
            "used_bmo_content": ["Policy B"]
        }
        metadata = strategy.extract_metadata(raw)

        assert metadata["graph"] == "graph_data"
        assert metadata["references"] == ["ref1", "ref2"]
        assert metadata["used_bmo_content"] == ["Policy B"]


class TestChatbotClientFactory:
    """Test factory pattern for creating strategies."""

    def test_create_vanilla_rag_strategy(self):
        config = ChatbotConfig(
            chatbot_type=ChatbotType.VANILLA_RAG,
            endpoint="https://example.com"
        )

        strategy = ChatbotClientFactory.create(config)

        assert isinstance(strategy, VanillaRAGStrategy)

    def test_create_graph_rag_strategy(self):
        config = ChatbotConfig(
            chatbot_type=ChatbotType.GRAPH_RAG,
            endpoint="https://example.com"
        )

        strategy = ChatbotClientFactory.create(config)

        assert isinstance(strategy, GraphRAGStrategy)

    def test_register_custom_strategy(self):
        from adaptive_synth_eval.clients.unified_chatbot import BaseChatbotStrategy
        
        class CustomStrategy(BaseChatbotStrategy):
            def build_payload(self, question: str, **kwargs):
                return {"custom_query": question}
            
            def extract_bot_response(self, raw_response):
                return raw_response.get("answer", "")
            
            def extract_metadata(self, raw_response):
                return {"custom_field": raw_response.get("custom")}

        ChatbotClientFactory.register_strategy(
            ChatbotType("custom"),
            CustomStrategy
        )

        config = ChatbotConfig(
            chatbot_type=ChatbotType("custom"),
            endpoint="https://custom.com"
        )

        strategy = ChatbotClientFactory.create(config)
        assert isinstance(strategy, CustomStrategy)

    def test_unsupported_type_raises_error(self):
        config = ChatbotConfig(
            chatbot_type=ChatbotType("nonexistent"),
            endpoint="https://example.com"
        )

        with pytest.raises(ValueError, match="Unsupported chatbot type"):
            ChatbotClientFactory.create(config)


class TestUnifiedChatbotClient:
    """Test the high-level unified client facade."""

    def test_create_vanilla_rag_client(self):
        config = ChatbotConfig(
            chatbot_type=ChatbotType.VANILLA_RAG,
            endpoint="https://vanilla.example.com"
        )

        client = UnifiedChatbotClient(config)

        assert client.chatbot_type == ChatbotType.VANILLA_RAG
        assert client.endpoint == "https://vanilla.example.com"
        assert isinstance(client.strategy, VanillaRAGStrategy)

    def test_create_graph_rag_client(self):
        config = ChatbotConfig(
            chatbot_type=ChatbotType.GRAPH_RAG,
            endpoint="https://graph.example.com"
        )

        client = UnifiedChatbotClient(config)

        assert client.chatbot_type == ChatbotType.GRAPH_RAG
        assert isinstance(client.strategy, GraphRAGStrategy)

    @patch('adaptive_synth_eval.clients.unified_chatbot.requests.post')
    def test_query_vanilla_rag(self, mock_post):
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "llm_response": "Parental leave is 12 weeks."
        }
        mock_response.headers = {"content-type": "application/json"}
        mock_post.return_value = mock_response

        config = ChatbotConfig(
            chatbot_type=ChatbotType.VANILLA_RAG,
            endpoint="https://vanilla.example.com/api"
        )
        client = UnifiedChatbotClient(config)

        response = client.query("How long is parental leave?")

        assert response.success is True
        assert response.bot_response == "Parental leave is 12 weeks."
        assert response.status_code == 200

    @patch('adaptive_synth_eval.clients.unified_chatbot.requests.post')
    def test_query_graph_rag(self, mock_post):
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "llm_response": "Graph-based answer here.",
            "graph": "graph_data",
            "references": ["ref1"]
        }
        mock_response.headers = {"content-type": "application/json"}
        mock_post.return_value = mock_response

        config = ChatbotConfig(
            chatbot_type=ChatbotType.GRAPH_RAG,
            endpoint="https://graph.example.com/api"
        )
        client = UnifiedChatbotClient(config)

        response = client.query("What does the graph say?")

        assert response.success is True
        assert response.bot_response == "Graph-based answer here."
        assert response.metadata.get("graph") == "graph_data"

    @patch('adaptive_synth_eval.clients.unified_chatbot.requests.post')
    def test_query_handles_error(self, mock_post):
        # Mock network error
        mock_post.side_effect = Exception("Connection timeout")

        config = ChatbotConfig(
            chatbot_type=ChatbotType.VANILLA_RAG,
            endpoint="https://vanilla.example.com/api"
        )
        client = UnifiedChatbotClient(config)

        response = client.query("Test question")

        assert response.success is False
        assert response.error == "Connection timeout"
        assert response.bot_response == ""


class TestCreateChatbotClient:
    """Test convenience function for quick client creation."""

    def test_create_vanilla_rag(self):
        client = create_chatbot_client(
            chatbot_type="vanilla_rag",
            endpoint="https://vanilla.example.com",
            timeout_seconds=30.0
        )

        assert client.chatbot_type == ChatbotType.VANILLA_RAG
        assert client.config.timeout_seconds == 30.0

    def test_create_graph_rag(self):
        client = create_chatbot_client(
            chatbot_type="graph_rag",
            endpoint="https://graph.example.com"
        )

        assert client.chatbot_type == ChatbotType.GRAPH_RAG


class TestIntegrationScenarios:
    """Integration-style tests showing real-world usage patterns."""

    @patch('adaptive_synth_eval.clients.unified_chatbot.requests.post')
    def test_switching_between_rag_types(self, mock_post):
        """Demonstrate easy switching between Vanilla and Graph RAG."""

        # Mock responses
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"llm_response": "Answer"}
        mock_response.headers = {"content-type": "application/json"}
        mock_post.return_value = mock_response

        # Create both clients
        vanilla_client = create_chatbot_client(
            "vanilla_rag",
            "https://vanilla.example.com/api"
        )

        graph_client = create_chatbot_client(
            "graph_rag",
            "https://graph.example.com/api"
        )

        # Query both
        vanilla_response = vanilla_client.query("Question 1")
        graph_response = graph_client.query("Question 2")

        # Both should work with same interface
        assert vanilla_response.success is True
        assert graph_response.success is True
        assert hasattr(vanilla_response, 'bot_response')
        assert hasattr(graph_response, 'bot_response')

    @patch('adaptive_synth_eval.clients.unified_chatbot.requests.post')
    def test_batch_queries_same_interface(self, mock_post):
        """Show that different chatbot types use identical query interface."""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"llm_response": "Batch answer"}
        mock_response.headers = {"content-type": "application/json"}
        mock_post.return_value = mock_response

        questions = ["Q1", "Q2", "Q3"]
        client = create_chatbot_client("vanilla_rag", "https://example.com/api")

        responses = [client.query(q) for q in questions]

        assert len(responses) == 3
        assert all(r.success for r in responses)
        assert all(r.bot_response == "Batch answer" for r in responses)
