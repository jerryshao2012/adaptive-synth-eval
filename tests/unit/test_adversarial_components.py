from adversarial_response_engine.core.token_budget import TokenBudgetManager
from adversarial_response_engine.engine.attack_agent import AttackAgent
from adversarial_response_engine.engine.components import SafetyJudge


def test_adversarial_imports_and_construct():
    """Verify that we can import and construct core classes of the adversarial engine."""
    manager = TokenBudgetManager(max_total_tokens=5000)
    assert manager.max_total_tokens == 5000
    assert manager.used_total_tokens == 0

    # Test the existence/import of the components
    assert AttackAgent is not None
    assert SafetyJudge is not None
