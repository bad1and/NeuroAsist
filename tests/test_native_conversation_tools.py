"""Actual provider tool protocol, including the failed prerelease voice dialogue."""
import json
import asyncio
from types import SimpleNamespace as NS

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.llm.providers import deepseek as module
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.environment.search_service import SearchService, SearchResult
from tests.test_deepseek_provider import FakeClient, FakeStream, _settings, _chunk, _completion
from tests.test_search_recovery import Environment, History, Lookup, ReplayLLM


@pytest.fixture
def anyio_backend():
    return "asyncio"


QUERY = "Яндекс дата-центры последние новости атака октябрь 2026"
QUESTION = "ну то что вот с яндекс дтентра недавно ну это недавно последние новости какие то"
PROMISE = "Так, «прилёт» — это уже зацепка, а не «что-то недавно». Щас гляну, что там по удару."
CONTEXT = [ChatMessage(role="user", content="ирис приветик"),
           ChatMessage(role="assistant", content="Приветик. Опять ты с дата-центром, что ли?"),
           ChatMessage(role="user", content="ну вот да хочу пообсуждать"),
           ChatMessage(role="assistant", content="Только я по нему конкретики не нарыла — выдача общими подборками плюётся."),
           ChatMessage(role="user", content="ну вот то что недавно произошло")]


def call(arguments=None, id="call-search"):
    return NS(id=id, type="function", function=NS(name="web_search", arguments=json.dumps(arguments or {"query": QUERY})))


def completion(calls):
    return NS(choices=[NS(message=NS(content=None, tool_calls=calls), finish_reason="tool_calls")],
              model="deepseek-flash", usage=NS(prompt_tokens=10, completion_tokens=20, total_tokens=30))


def tool_chunk(name=None, arguments=None, id=None, index=0):
    return NS(choices=[NS(delta=NS(content=None, tool_calls=[NS(index=index, id=id,
        function=NS(name=name, arguments=arguments))]), finish_reason=None)], model="deepseek-flash", usage=None)


@pytest.mark.anyio
async def test_native_batch_call_preserves_id_and_sends_actual_tool_result(monkeypatch):
    fake = FakeClient([completion([call()]), _completion('{"reply":"Проверка завершена.","emotion":"neutral","intent":"question"}')])
    monkeypatch.setattr(module, "_shared_client", lambda *_: fake)
    lookup = Lookup()
    agent = CharacterAgent(DeepSeekProvider(_settings()), History(CONTEXT), 12, situational_coordinator=Environment(lookup))
    assert (await agent.handle_user_message("s", QUESTION, persist_reply=False))["reply"] == "Проверка завершена."
    assert [q for q, _ in lookup.calls] == [QUERY]
    first, final = fake.completions.calls
    assert first["tool_choice"] == "auto" and first["tools"][0]["function"]["name"] == "web_search"
    assert "tools" not in final
    assert any(m["role"] == "assistant" and m.get("tool_calls", [])[0]["id"] == "call-search" for m in final["messages"] if m.get("tool_calls"))
    assert any(m["role"] == "tool" and m["tool_call_id"] == "call-search" and "новый герой" in m["content"] for m in final["messages"])


@pytest.mark.anyio
async def test_call_id_survives_intermediate_search_assessment(monkeypatch):
    fake = FakeClient([completion([call()]), _completion('{"enough":true,"source_ids":["S1"],"query":""}'),
                       _completion('{"reply":"Проверка завершена.","emotion":"neutral","intent":"question"}')])
    monkeypatch.setattr(module, "_shared_client", lambda *_: fake)
    class Search(SearchService):
        async def search(self, query, **options):
            return self._snapshot(query, status="ok", results=[SearchResult(
                "Яндекс дата-центр: событие", "Подтверждение события по искомому объекту.", "https://example.com/event",
                page_text="Яндекс подтвердил событие в дата-центре.", page_status="read")])
    service = Search()
    try:
        agent = CharacterAgent(DeepSeekProvider(_settings()), History(CONTEXT), 12, situational_coordinator=Environment(service))
        await agent.handle_user_message("s", QUESTION, persist_reply=False)
        assert len(fake.completions.calls) == 3
        assert any(m["role"] == "tool" and m["tool_call_id"] == "call-search" for m in fake.completions.calls[-1]["messages"])
    finally:
        await service.close()


@pytest.mark.anyio
async def test_streamed_native_arguments_and_preamble_never_reach_voice(monkeypatch):
    arguments = json.dumps({"query": QUERY}, ensure_ascii=False)
    decision = [_chunk("Так, щас гляну."), tool_chunk("web_search", id="call-search")]
    decision += [tool_chunk(arguments=char) for char in arguments]
    decision += [_chunk(finish_reason="tool_calls", usage=NS(prompt_tokens=10, completion_tokens=20, total_tokens=30))]
    fake = FakeClient([FakeStream(decision), FakeStream([_chunk("Проверка завершена."), _chunk(finish_reason="stop")])])
    monkeypatch.setattr(module, "_shared_client", lambda *_: fake)
    lookup = Lookup()
    agent = CharacterAgent(DeepSeekProvider(_settings()), History(CONTEXT), 12, situational_coordinator=Environment(lookup))
    visible = "".join([p async for p in agent.stream_user_message("s", QUESTION, persist_reply=False)])
    assert visible == "Проверка завершена." and len(lookup.calls) == 1
    assert agent.last_skill_metadata["status"] == "ok"
    assert fake.completions.calls[-1]["messages"][-2]["role"] == "tool"


@pytest.mark.anyio
@pytest.mark.parametrize("question", ["ну вот то что недавно произошло", QUESTION, "ну прилет блять по яндекс дотацентрам нахуй"])
async def test_native_dialogue_never_prefetches_raw_recognition_text(question):
    provider = DeepSeekProvider(_settings())
    lookup = Lookup()
    agent = CharacterAgent(provider, History(), 12, situational_coordinator=Environment(lookup))
    assert await agent._plan_turn_search("s", question, CONTEXT) is None
    assert not lookup.calls and not agent._search_performed and agent._skills.tools()


@pytest.mark.anyio
async def test_parallel_native_calls_are_rejected_without_partial_execution(monkeypatch):
    fake = FakeClient([completion([call(id="a"), call(id="b")]), _completion('{"reply":"Проверка не выполнена.","emotion":"neutral","intent":"question"}')])
    monkeypatch.setattr(module, "_shared_client", lambda *_: fake)
    lookup = Lookup()
    agent = CharacterAgent(DeepSeekProvider(_settings()), History(), 12, situational_coordinator=Environment(lookup))
    await agent.handle_user_message("s", QUESTION, persist_reply=False)
    assert not lookup.calls
    assert {m["tool_call_id"] for m in fake.completions.calls[-1]["messages"] if m["role"] == "tool"} == {"a", "b"}


@pytest.mark.anyio
async def test_unfulfilled_promise_with_arbitrary_preamble_is_completed(monkeypatch):
    fake = FakeClient([_completion(json.dumps({"reply": PROMISE})), completion([call()]),
                       _completion('{"reply":"Проверка завершена.","emotion":"neutral","intent":"question"}')])
    monkeypatch.setattr(module, "_shared_client", lambda *_: fake)
    lookup = Lookup()
    agent = CharacterAgent(DeepSeekProvider(_settings()), History(CONTEXT), 12, situational_coordinator=Environment(lookup))
    result = await agent.handle_user_message("s", "ну прилет по яндекс дотацентрам", persist_reply=False)
    assert "Проверка завершена" in result["reply"] and len(lookup.calls) == 1 and len(fake.completions.calls) == 3


def test_false_empty_results_claim_without_lookup_is_rejected():
    agent = CharacterAgent(ReplayLLM([]), History(), 12)
    assert agent._truthful_search_reply("По нему конкретики не нарыла — выдача общими подборками плюётся.") == "В этом ответе поиск не выполнялся."
    assert agent._truthful_search_reply("Свежих новостей по Яндексу в выдаче нет.") == "В этом ответе поиск не выполнялся."


@pytest.mark.anyio
async def test_native_voice_lookup_does_not_buy_an_extra_bridge_decision(monkeypatch):
    from apps.backend.app.agents.character import agent as agent_module
    monkeypatch.setattr(agent_module, "_SEARCH_ACK_DELAY_SECONDS", .001)
    decision = FakeStream([tool_chunk("web_search", json.dumps({"query": QUERY}), "call-search"),
                           _chunk(finish_reason="tool_calls")])
    fake = FakeClient([decision, FakeStream([_chunk("Проверка завершена."), _chunk(finish_reason="stop")])])
    monkeypatch.setattr(module, "_shared_client", lambda *_: fake)
    class SlowLookup(Lookup):
        async def search(self, query, **options):
            await asyncio.sleep(.02)
            return await super().search(query, **options)
    agent = CharacterAgent(DeepSeekProvider(_settings()), History(CONTEXT), 12, situational_coordinator=Environment(SlowLookup()))
    async def unexpected_bridge():
        raise AssertionError("Native tools must reuse the initial decision")
    monkeypatch.setattr(agent, "_generate_search_bridge", unexpected_bridge)
    assert "".join([p async for p in agent.stream_user_message("s", QUESTION, persist_reply=False)]) == "Проверка завершена."
    assert len(fake.completions.calls) == 2
