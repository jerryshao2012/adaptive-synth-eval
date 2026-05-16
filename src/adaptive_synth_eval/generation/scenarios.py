from adaptive_synth_eval.config.schemas import Scenario


def scenario_instruction(scenario: Scenario) -> str:
    topics = ", ".join(scenario.expected_retrieval_topics)
    return f"Intent: {scenario.intent}. Domain: {scenario.domain}. Expected topics: {topics}."
