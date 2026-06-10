import json
import sys
import types

from adaptive_synth_eval.adversarial_response_engine.providers.llm_backends import make_bedrock_backend


class _FakeBody:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload)


class _FakeBedrockClient:
    def __init__(self):
        self.calls = []
        self.raise_on_converse = None
        self.raise_unprefixed_on_demand = False

    def converse(self, **kwargs):
        self.calls.append(("converse", kwargs))
        model_id = kwargs.get("modelId", "")
        if self.raise_unprefixed_on_demand and "." in model_id and not model_id.startswith(("us.", "eu.", "global.")):
            raise Exception(
                "ValidationException: Invocation of model ID deepseek.r1-v1:0 with on-demand throughput isn’t supported. "
                "Retry your request with the ID or ARN of an inference profile that contains this model."
            )
        if self.raise_on_converse is not None:
            raise self.raise_on_converse
        return {
            "output": {
                "message": {
                    "content": [{"text": "{\"ok\": true}"}],
                }
            },
            "usage": {"inputTokens": 11, "outputTokens": 7},
        }

    def invoke_model(self, **kwargs):
        self.calls.append(("invoke_model", kwargs))
        if kwargs.get("modelId", "").startswith("us.moonshot"):
            return {
                "body": _FakeBody(
                    {
                        "choices": [{"message": {"content": "{\"ok\": true}"}}],
                        "usage": {"prompt_tokens": 13, "completion_tokens": 8},
                    }
                )
            }
        return {
            "body": _FakeBody(
                {
                    "results": [{"outputText": "{\"ok\": true}", "tokenCount": 5}],
                    "inputTextTokenCount": 9,
                }
            )
        }


class _FakeBoto3Module:
    def __init__(self, client):
        self._client = client

    def client(self, *_args, **_kwargs):
        return self._client


class _FakeConfig:
    def __init__(self, **_kwargs):
        pass


def test_bedrock_backend_uses_converse_for_us_moonshot(monkeypatch):
    fake_client = _FakeBedrockClient()
    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3Module(fake_client))
    monkeypatch.setitem(sys.modules, "botocore.config", types.SimpleNamespace(Config=_FakeConfig))

    call_fn = make_bedrock_backend(model="us.moonshot.kimi-k2-thinking", region="us-east-1", max_tokens=123)
    result = call_fn("sys", "user")

    assert fake_client.calls[0][0] == "converse"
    converse_kwargs = fake_client.calls[0][1]
    assert converse_kwargs["modelId"] == "us.moonshot.kimi-k2-thinking"
    assert converse_kwargs["inferenceConfig"]["maxTokens"] == 123
    assert result["content"] == "{\"ok\": true}"
    assert result["usage"]["prompt_tokens"] == 11
    assert result["usage"]["completion_tokens"] == 7


def test_bedrock_backend_falls_back_to_invoke_model_for_invalid_converse_model(monkeypatch):
    fake_client = _FakeBedrockClient()
    fake_client.raise_on_converse = Exception("ValidationException: The provided model identifier is invalid")
    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3Module(fake_client))
    monkeypatch.setitem(sys.modules, "botocore.config", types.SimpleNamespace(Config=_FakeConfig))

    call_fn = make_bedrock_backend(model="us.moonshot.kimi-k2-thinking", region="us-east-1", max_tokens=123)
    result = call_fn("sys", "user")

    assert fake_client.calls[0][0] == "converse"
    assert fake_client.calls[1][0] == "invoke_model"
    assert result["content"] == "{\"ok\": true}"
    assert result["usage"]["prompt_tokens"] == 13
    assert result["usage"]["completion_tokens"] == 8


def test_bedrock_backend_uses_invoke_model_for_amazon_titan(monkeypatch):
    fake_client = _FakeBedrockClient()
    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3Module(fake_client))
    monkeypatch.setitem(sys.modules, "botocore.config", types.SimpleNamespace(Config=_FakeConfig))

    call_fn = make_bedrock_backend(model="amazon.titan-text-express-v1", region="us-east-1", max_tokens=256)
    result = call_fn("sys", "user")

    assert fake_client.calls[0][0] == "invoke_model"
    invoke_kwargs = fake_client.calls[0][1]
    assert invoke_kwargs["modelId"] == "amazon.titan-text-express-v1"
    assert result["content"] == "{\"ok\": true}"
    assert result["usage"]["prompt_tokens"] == 9
    assert result["usage"]["completion_tokens"] == 5


def test_bedrock_backend_retries_with_profile_prefix_for_on_demand_error(monkeypatch):
    fake_client = _FakeBedrockClient()
    fake_client.raise_unprefixed_on_demand = True
    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3Module(fake_client))
    monkeypatch.setitem(sys.modules, "botocore.config", types.SimpleNamespace(Config=_FakeConfig))

    call_fn = make_bedrock_backend(model="deepseek.r1-v1:0", region="us-east-1", max_tokens=123)
    result = call_fn("sys", "user")

    assert fake_client.calls[0][0] == "converse"
    assert fake_client.calls[0][1]["modelId"] == "deepseek.r1-v1:0"
    assert fake_client.calls[1][0] == "converse"
    assert fake_client.calls[1][1]["modelId"] == "us.deepseek.r1-v1:0"
    assert result["content"] == "{\"ok\": true}"
