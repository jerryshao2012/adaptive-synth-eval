from unittest.mock import patch

from adaptive_synth_eval.clients.llm import LLMClient, LLMResult
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
    with patch.object(simulator.llm_client, "complete") as mock_complete:
        mock_complete.return_value = LLMResult(content="", raw={"mock": True}, error="llm_disabled")
        turn = simulator.generate_turn(turn_id=1, previous_bot_response=None, behavior_override="aggressive")

    assert turn.generation_metadata["behavior_mode"] == "aggressive"
    assert "I need a clear answer now" in turn.user_message


def test_user_simulator_with_markdown_memory(tmp_path):
    persona = Persona(
        persona_id="P_MEM_TEST",
        role="tester",
        location="Canada",
        seniority="senior",
        communication_style="polite",
        hr_familiarity="high",
        privacy_sensitivity="low",
    )
    scenario = Scenario(
        scenario_id="S001",
        domain="benefits",
        intent="enroll_spouse",
        expected_retrieval_topics=["spouse_benefits"],
        failure_injection=FailureInjection(),
        success_criteria={"answers_grounded_in_policy": True},
    )

    memory_file = tmp_path / "personas" / "P_MEM_TEST_memory.md"
    simulator = UserSimulator(persona=persona, scenario=scenario, turn_count=3, seed=42, memory_file=memory_file)

    # 1. Verify memory is loaded and initialized with baseline demographics
    assert simulator.memory is not None
    assert simulator.memory.demographics["role"] == "tester"
    assert simulator.memory.demographics["location"] == "Canada"

    # 2. Generate Turn 1 and verify profile delta extraction
    # We patch LLM complete so it returns a message containing profile information
    with patch.object(simulator.llm_client, "complete") as mock_complete:
        mock_complete.return_value = LLMResult(
            content="Hi, my name is Jerry. I prefer standard dental coverage.",
            raw={},
        )
        turn = simulator.generate_turn(turn_id=1, previous_bot_response=None)

    assert "Jerry" in turn.user_message
    assert simulator.memory.demographics["name"] == "Jerry"
    assert simulator.memory.preferences["stated_preference"] == "standard dental coverage"
    assert memory_file.exists()

    # 3. Simulate bot response and next turn
    with patch.object(simulator.llm_client, "complete") as mock_complete:
        mock_complete.return_value = LLMResult(
            content="I speak French. This is my preferred language. Here is my email test@example.com.",
            raw={},
        )
        # Previous bot response matches something that has no delta, but registers in history
        turn2 = simulator.generate_turn(turn_id=2, previous_bot_response="Hello Jerry, what information do you need?")

    assert simulator.memory.settings["language"] == "french"
    assert simulator.memory.demographics["email"] == "test@example.com"
    assert len(simulator.memory.recent_window) == 3  # User Turn 1, Agent Response, User Turn 2

    # 4. Save conversation summary and clear recent window
    simulator.save_conversation_summary_to_long_term_recall()
    assert len(simulator.memory.recent_window) == 0
    assert len(simulator.memory.long_term_recall) == 1
    assert "spouse" in simulator.memory.long_term_recall[0] or "benefits" in simulator.memory.long_term_recall[0]

    # 5. Reload memory in a new simulator and verify persistence
    simulator2 = UserSimulator(persona=persona, scenario=scenario, turn_count=3, seed=42, memory_file=memory_file)
    assert simulator2.memory.demographics["name"] == "Jerry"
    assert simulator2.memory.demographics["email"] == "test@example.com"
    assert simulator2.memory.preferences["stated_preference"] == "standard dental coverage"
    assert len(simulator2.memory.long_term_recall) == 1


def test_llm_client_content_filter_error_returns_classified_fallback():
    client = LLMClient(enabled=True, model_provider="azure_openai")

    class _BlockedModel:
        def invoke(self, prompt):
            raise RuntimeError("ResponsibleAIPolicyViolation: content_filter")

    with patch.object(client, "_get_model", return_value=_BlockedModel()):
        result = client.complete("test prompt")

    assert result.error == "content_filter_blocked"
    assert result.raw.get("error_code") == "content_filter"


def test_first_turn_sanitizes_continuation_language():
    persona = Persona(
        persona_id="P_FIRST_CONTACT",
        role="new_employee",
        location="Canada",
        seniority="junior",
        communication_style="polite",
        hr_familiarity="low",
        privacy_sensitivity="medium",
    )
    scenario = Scenario(
        scenario_id="S_FIRST_CONTACT",
        domain="tfsa_eligibility",
        intent="check_eligibility_and_limits",
        expected_retrieval_topics=["eligibility"],
        failure_injection=FailureInjection(),
        success_criteria={"answers_grounded_in_policy": True},
    )

    simulator = UserSimulator(persona=persona, scenario=scenario, turn_count=3, seed=7)
    with patch.object(simulator.llm_client, "complete") as mock_complete:
        mock_complete.return_value = LLMResult(
            content="Got it. One more thing: what should I do next based on what you said?",
            raw={},
        )
        turn = simulator.generate_turn(turn_id=1, previous_bot_response=None)

    assert "got it" not in turn.user_message.lower()
    assert "one more thing" not in turn.user_message.lower()
    assert turn.user_message.startswith("Hi, I need help with")


def test_recent_window_is_cleared_when_starting_new_conversation(tmp_path):
    persona = Persona(
        persona_id="P_RECENT_WINDOW",
        role="new_employee",
        location="Canada",
        seniority="junior",
        communication_style="polite",
        hr_familiarity="low",
        privacy_sensitivity="medium",
    )
    scenario = Scenario(
        scenario_id="S_RECENT_WINDOW",
        domain="tfsa_eligibility",
        intent="check_eligibility_and_limits",
        expected_retrieval_topics=["eligibility"],
        failure_injection=FailureInjection(),
        success_criteria={"answers_grounded_in_policy": True},
    )
    memory_file = tmp_path / "personas" / "P_RECENT_WINDOW_memory.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(
        "\n".join([
            "# Persona Memory: P_RECENT_WINDOW",
            "",
            "## Demographics",
            "- role: new_employee",
            "",
            "## Preferences",
            "",
            "## Settings",
            "",
            "## Summary Notes",
            "- Interacted regarding tfsa_eligibility.",
            "",
            "## Long Term Recall",
            "",
            "## Recent Window",
            "- User: Got it. One more thing: can you confirm eligibility?",
            "- Assistant: Sure, based on what we discussed...",
            "",
        ]),
        encoding="utf-8",
    )

    simulator = UserSimulator(
        persona=persona,
        scenario=scenario,
        turn_count=3,
        seed=11,
        memory_file=memory_file,
    )

    assert simulator.history == []
    assert simulator.memory is not None
    assert simulator.memory.recent_window == []
