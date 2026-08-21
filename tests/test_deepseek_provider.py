import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, APITimeoutError, OpenAIError

from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import (
    ChatMessage,
    LLMProviderError,
    LLMResponse,
    llm_call_purpose,
)
from apps.backend.app.llm.providers import deepseek as deepseek_module
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.llm.telemetry import llm_telemetry


class FakeCompletions:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    def __init__(self, results: list[object]) -> None:
        self.completions = FakeCompletions(results)
        self.chat = SimpleNamespace(completions=self.completions)


class FakeStream:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        item = self.chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, deepseek_api_key="test-key", **overrides)


def _completion(
    content: str | None,
    *,
    finish_reason: str = "stop",
    usage: object | None = None,
    model: str = "deepseek-test",
):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
        model=model,
    )


def _chunk(
    content: str | None = None,
    *,
    finish_reason: str | None = None,
    usage: object | None = None,
    choices: bool = True,
):
    chunk_choices = []
    if choices:
        chunk_choices = [
            SimpleNamespace(
                delta=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
    return SimpleNamespace(choices=chunk_choices, usage=usage, model="deepseek-stream")


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="hello")]


def test_generate_disables_thinking_caps_output_and_collects_usage(monkeypatch) -> None:
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=30,
        total_tokens=150,
        prompt_cache_hit_tokens=80,
        prompt_cache_miss_tokens=40,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=7),
    )
    fake = FakeClient([_completion('{"reply":"ok"}', usage=usage)])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(_settings(llm_chat_json_max_tokens=777))

    result = asyncio.run(provider.generate(_messages()))

    assert isinstance(result, LLMResponse)
    assert result.purpose == "chat_json"
    assert result.finish_reason == "stop"
    assert result.attempts == 1
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert result.usage is not None
    assert result.usage.model_dump() == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
        "reasoning_tokens": 7,
        "prompt_cache_hit_tokens": 80,
        "prompt_cache_miss_tokens": 40,
    }
    call = fake.completions.calls[0]
    assert call["max_tokens"] == 777
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert call["response_format"] == {"type": "json_object"}
    assert provider.last_response == result
    assert provider.last_call_metrics is not None
    assert provider.last_call_metrics.succeeded is True


@pytest.mark.parametrize(
    ("purpose", "setting_name", "budget", "thinking"),
    [
        ("memory", "llm_memory_max_tokens", 701, "disabled"),
        ("reflection", "llm_reflection_max_tokens", 211, "disabled"),
        ("adjudication", "llm_adjudication_max_tokens", 233, "disabled"),
        ("coding", "llm_coding_max_tokens", 4_321, "enabled"),
    ],
)
def test_generate_uses_purpose_profile(
    monkeypatch, purpose: str, setting_name: str, budget: int, thinking: str
) -> None:
    fake = FakeClient([_completion("{}")])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(
        _settings(**{setting_name: budget}),
        purpose=purpose,
    )

    result = asyncio.run(provider.generate_structured(_messages()))

    assert result.purpose == purpose
    assert fake.completions.calls[0]["max_tokens"] == budget
    assert fake.completions.calls[0]["extra_body"] == {
        "thinking": {"type": thinking}
    }


def test_semantic_retry_context_gets_its_own_telemetry_purpose(monkeypatch) -> None:
    fake = FakeClient([_completion("{}")])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(
        _settings(llm_memory_max_tokens=654),
        purpose="memory",
    )

    with llm_call_purpose("memory_repair"):
        result = asyncio.run(provider.generate_structured(_messages()))

    assert result.purpose == "memory_repair"
    assert fake.completions.calls[0]["max_tokens"] == 654
    assert fake.completions.calls[0]["extra_body"] == {
        "thinking": {"type": "disabled"}
    }


def test_generate_does_not_retry_empty_semantic_response(monkeypatch) -> None:
    first_usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=2,
        total_tokens=102,
        reasoning_tokens=1,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=100,
    )
    fake = FakeClient([_completion("", finish_reason="stop", usage=first_usage)])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(_settings())
    llm_telemetry.reset()

    result = asyncio.run(provider.generate(_messages()))

    assert len(fake.completions.calls) == 1
    assert result.content == ""
    assert provider.last_call_metrics is not None
    assert provider.last_call_metrics.attempts == 1
    assert provider.last_call_metrics.usage is not None
    assert provider.last_call_metrics.usage.total_tokens == 102
    records = llm_telemetry.snapshot("5m")
    assert len(records) == 1
    assert records[0].logical_attempt == 1
    assert records[0].status == "empty"
    assert records[0].total == 102
    assert records[0].input_chars == len("hello")
    assert records[0].message_count == 1
    assert records[0].thinking is False
    assert records[0].latency >= 0
    llm_telemetry.reset()


def test_generate_has_one_total_retry_layer(monkeypatch) -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    fake = FakeClient([APITimeoutError(request=request), _completion("{}")])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(_settings())

    result = asyncio.run(provider.generate(_messages()))

    assert len(fake.completions.calls) == 2
    assert result.attempts == 2


def test_generate_does_not_retry_non_retryable_status(monkeypatch) -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(401, request=request)
    error = APIStatusError("unauthorized", response=response, body={})
    fake = FakeClient([error])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(_settings())

    with pytest.raises(LLMProviderError, match="HTTP 401"):
        asyncio.run(provider.generate(_messages()))

    assert len(fake.completions.calls) == 1
    assert provider.last_call_metrics is not None
    assert provider.last_call_metrics.attempts == 1
    assert provider.last_call_metrics.succeeded is False


def test_stream_requests_usage_and_captures_usage_only_final_chunk(monkeypatch) -> None:
    usage = SimpleNamespace(
        prompt_tokens=44,
        completion_tokens=8,
        total_tokens=52,
        reasoning_tokens=0,
        prompt_cache_hit_tokens=40,
        prompt_cache_miss_tokens=4,
    )
    stream = FakeStream(
        [
            _chunk("hello "),
            _chunk("world", finish_reason="stop"),
            _chunk(choices=False, usage=usage),
        ]
    )
    fake = FakeClient([stream])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(_settings(llm_chat_live_max_tokens=321))

    async def consume() -> list[str]:
        return [item async for item in provider.stream(_messages())]

    assert asyncio.run(consume()) == ["hello ", "world"]
    call = fake.completions.calls[0]
    assert call["stream_options"] == {"include_usage": True}
    assert call["max_tokens"] == 321
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert provider.last_response is not None
    assert provider.last_response.content == "hello world"
    assert provider.last_response.finish_reason == "stop"
    assert provider.last_response.purpose == "chat_live"
    assert provider.last_response.usage is not None
    assert provider.last_response.usage.prompt_cache_hit_tokens == 40


def test_stream_never_retries_after_yielding_content(monkeypatch) -> None:
    stream = FakeStream([_chunk("visible"), OpenAIError("broken stream")])
    fake = FakeClient([stream, FakeStream([_chunk("duplicate")])])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(_settings())

    async def consume() -> list[str]:
        values: list[str] = []
        async for value in provider.stream(_messages()):
            values.append(value)
        return values

    with pytest.raises(LLMProviderError, match="streaming request failed"):
        asyncio.run(consume())

    assert len(fake.completions.calls) == 1
    assert provider.last_call_metrics is not None
    assert provider.last_call_metrics.attempts == 1
    assert provider.last_call_metrics.succeeded is False


def test_closing_stream_records_cancelled_usage_without_content(monkeypatch) -> None:
    fake = FakeClient([FakeStream([_chunk("visible"), _chunk("unused")])])
    monkeypatch.setattr(deepseek_module, "_shared_client", lambda *_: fake)
    provider = DeepSeekProvider(_settings())
    llm_telemetry.reset()

    async def consume_one_and_close() -> None:
        iterator = provider.stream(_messages())
        assert await anext(iterator) == "visible"
        await iterator.aclose()

    asyncio.run(consume_one_and_close())

    records = llm_telemetry.snapshot("5m")
    assert len(records) == 1
    assert records[0].status == "cancelled"
    assert records[0].error_type == "GeneratorExit"
    assert provider.last_call_metrics is not None
    assert provider.last_call_metrics.succeeded is False
    llm_telemetry.reset()


def test_shared_client_disables_sdk_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class StubAsyncOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    async def create_client() -> None:
        deepseek_module._CLIENTS.clear()
        deepseek_module._shared_client("key", "https://example.test", 12.0)
        deepseek_module._CLIENTS.clear()

    monkeypatch.setattr(deepseek_module, "AsyncOpenAI", StubAsyncOpenAI)
    asyncio.run(create_client())

    assert captured["max_retries"] == 0


def test_llm_response_remains_backwards_compatible() -> None:
    response = LLMResponse(content="ok", model="legacy")

    assert response.usage is None
    assert response.finish_reason is None
    assert response.latency_ms is None
    assert response.attempts == 1
    assert response.purpose is None
