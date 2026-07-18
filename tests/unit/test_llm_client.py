from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage

from adaptive_synth_eval.clients.llm import LLMClient


class _FakeModel:
    def __init__(self):
        self.invocations = []
        self.bind_calls = []

    def bind(self, **kwargs):
        self.bind_calls.append(kwargs)
        return self

    def invoke(self, payload):
        self.invocations.append(payload)
        return SimpleNamespace(content='{"score": 1.0}', usage_metadata={"total_tokens": 3})


def test_complete_remains_backward_compatible_with_plain_prompt(monkeypatch):
    client = LLMClient(enabled=True, model_provider="openai")
    model = _FakeModel()
    monkeypatch.setattr(client, "_get_model", lambda: model)

    result = client.complete("legacy prompt")

    assert result.error is None
    assert model.invocations == ["legacy prompt"]
    assert model.bind_calls == []


def test_complete_uses_role_separated_messages_and_native_json_for_openai(monkeypatch):
    client = LLMClient(enabled=True, model_provider="openai")
    model = _FakeModel()
    monkeypatch.setattr(client, "_get_model", lambda: model)

    result = client.complete(
        '{"user_message": "hello"}',
        system_prompt="Return exact JSON.",
        json_mode=True,
    )

    assert result.error is None
    assert model.bind_calls == [{"response_format": {"type": "json_object"}}]
    messages = model.invocations[0]
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "Return exact JSON."
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == '{"user_message": "hello"}'


def test_complete_uses_validator_only_transport_for_anthropic(monkeypatch):
    client = LLMClient(enabled=True, model_provider="anthropic")
    model = _FakeModel()
    monkeypatch.setattr(client, "_get_model", lambda: model)

    client.complete("payload", system_prompt="system", json_mode=True)

    assert model.bind_calls == []
    messages = model.invocations[0]
    assert [message.content for message in messages] == ["system", "payload"]
