from unittest.mock import patch

from adaptive_synth_eval.clients.llm import LLMClient
from adaptive_synth_eval.config.schemas import FailureInjection, Persona, Scenario
from adaptive_synth_eval.generation.turns import UserSimulator, generate_turns


def test_generate_turns_applies_failure_modes_and_metadata():
    persona = Persona(
        persona_id="P001",
        role="new_employee",
        location="Canada",
        seniority="junior",
        communication_style="confused_but_polite",
        hr_familiarity="low",
        privacy_sensitivity="medium",
    )
    scenario = Scenario(
        scenario_id="S001",
        domain="parental_leave_policy",
        intent="understand_eligibility",
        expected_retrieval_topics=["parental_leave"],
        failure_injection=FailureInjection(ambiguity=1.0, typos=1.0, missing_information=1.0),
        success_criteria={"answers_grounded_in_policy": True},
    )

    turns = generate_turns(persona, scenario, turn_count=3, seed=1)

    assert len(turns) == 3
    assert all(turn.user_message for turn in turns)
    assert {"ambiguity", "missing_information"}.issubset(set(turns[0].applied_failure_modes))
    assert "typos" in turns[0].applied_failure_modes


def test_llm_client_disabled_by_default():
    """Test that LLM client returns mock response when disabled."""
    client = LLMClient(enabled=False)
    result = client.complete("test prompt")

    assert result.error == "llm_disabled"
    assert result.raw["mock"] is True
    assert result.content == ""


def test_llm_client_no_provider_configured():
    """Test that LLM client handles missing provider gracefully."""
    with patch.dict('os.environ', {}, clear=True):
        client = LLMClient(enabled=True)
        result = client.complete("test prompt")

        assert result.error == "no_provider_configured"
        assert result.raw["mock"] is True


def test_llm_client_auto_detects_azure_provider():
    """Test that LLM client auto-detects Azure OpenAI provider."""
    with patch.dict('os.environ', {
        'AZURE_OPENAI_ENDPOINT': 'https://test.openai.azure.com/',
        'AZURE_OPENAI_DEPLOYMENT': 'gpt-4',
        'AZURE_OPENAI_API_KEY': 'test-key'
    }):
        client = LLMClient(enabled=False)
        assert client.model_provider == "azure_openai"


def test_llm_client_auto_detects_anthropic_provider():
    """Test that LLM client auto-detects Anthropic provider."""
    with patch.dict('os.environ', {
        'ANTHROPIC_API_KEY': 'test-key',
        'MODEL_NAME': 'claude-sonnet-4'
    }):
        client = LLMClient(enabled=False)
        assert client.model_provider == "anthropic"


def test_llm_client_auto_detects_openai_provider():
    """Test that LLM client auto-detects OpenAI provider."""
    with patch.dict('os.environ', {
        'OPENAI_API_KEY': 'test-key',
        'MODEL_NAME': 'gpt-4o-mini'
    }):
        client = LLMClient(enabled=False)
        assert client.model_provider == "openai"


def test_llm_client_auto_detects_ollama_provider():
    """Test that LLM client auto-detects Ollama provider."""
    with patch.dict('os.environ', {
        'OLLAMA_BASE_URL': 'http://localhost:11434',
        'OLLAMA_MODEL': 'llama3'
    }):
        client = LLMClient(enabled=False)
        assert client.model_provider == "ollama"


def test_generate_turn_behavior_override_changes_fallback_and_metadata():
    persona = Persona(
        persona_id="P001",
        role="new_employee",
        location="Canada",
        seniority="junior",
        communication_style="confused_but_polite",
        hr_familiarity="low",
        privacy_sensitivity="medium",
    )
    scenario = Scenario(
        scenario_id="S001",
        domain="parental_leave_policy",
        intent="understand_eligibility",
        expected_retrieval_topics=["parental_leave"],
        failure_injection=FailureInjection(),
        success_criteria={"answers_grounded_in_policy": True},
    )

    simulator = UserSimulator(persona=persona, scenario=scenario, turn_count=3, seed=42)
    turn = simulator.generate_turn(turn_id=1, previous_bot_response=None, behavior_override="aggressive")

    assert turn.generation_metadata["behavior_mode"] == "aggressive"
    assert "I need a clear answer now" in turn.user_message
