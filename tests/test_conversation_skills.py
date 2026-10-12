"""Model-selected capabilities, including the prerelease Yandex conversation."""
import asyncio
import json

import pytest
from pydantic import BaseModel

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.search_intent import plan_search
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.skills.runtime import Skill, SkillCall, SkillRegistry, parse_skill
from tests.test_search_recovery import Environment, History, Lookup, ReplayLLM


@pytest.fixture
def anyio_backend():
    return "asyncio"


QUESTION = "ну ладно давай че там с этим теперь с дтентром яндекса"
PROMISE = "Опять дата-центр? Мы же только что про водяные знаки говорили. Ладно, щас гляну по свежаку."
CONTEXT = [ChatMessage(role="user", content="давай че там про водяные знаки в и"),
           ChatMessage(role="assistant", content="Говорили про водяные знаки SynthID.")]
CALL = {"name": "web_search", "arguments": {"query": "Яндекс дата-центр последние события"}}


def response(text, live):
    return text if live else json.dumps({"reply": text, "emotion": "neutral", "intent": "question"}, ensure_ascii=False)


def command(call, live):
    body = json.dumps(call, ensure_ascii=False)
    return "[[skill: " + body + "]]" if live else json.dumps({"skill": call}, ensure_ascii=False)


class ChunkedLLM(ReplayLLM):
    def __init__(self, replies, size):
        super().__init__(replies)
        self.size = size

    async def stream(self, messages):
        result = await self.generate(messages)
        for start in range(0, len(result.content), self.size):
            yield result.content[start:start + self.size]


async def answer(agent, text, live):
    if live:
        return "".join([part async for part in agent.stream_user_message("s", text, persist_reply=False)])
    return (await agent.handle_user_message("s", text, persist_reply=False))["reply"]


@pytest.mark.anyio
@pytest.mark.parametrize("live,size", [(False, 1000), (True, 1), (True, 7), (True, 1000)])
async def test_model_calls_search_without_keyword_gate_and_finishes_same_turn(live, size):
    assert plan_search(QUESTION, CONTEXT) is None
    llm = ChunkedLLM([command(CALL, live), response("Проверка завершена, вот результат.", live)], size)
    lookup = Lookup()
    agent = CharacterAgent(llm, History(CONTEXT), 12, situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
    visible = await answer(agent, QUESTION, live)
    assert "Проверка завершена" in visible and "[[" not in visible
    assert [query for query, _ in lookup.calls] == [CALL["arguments"]["query"]]
    assert len(llm.calls) == 2 and agent.token_metadata()["total_tokens"] == 24
    assert any("слова 'поищи' не обязательны" in m.content for m in llm.calls[0])
    assert any("новый герой" in m.content for m in llm.calls[1])  # The real handler result reaches the answer.


@pytest.mark.anyio
@pytest.mark.parametrize("live,size", [(False, 1000), (True, 1), (True, 7), (True, 1000)])
async def test_reported_promise_is_recovered_semantically(live, size):
    assert CharacterAgent._search_promise_only(PROMISE)
    llm = ChunkedLLM([response(PROMISE, live), command(CALL, False), response("Проверка завершена.", live)], size)
    lookup = Lookup()
    agent = CharacterAgent(llm, History(CONTEXT), 12, situational_coordinator=Environment(lookup))
    visible = await answer(agent, QUESTION, live)
    assert "Проверка завершена" in visible and "щас" not in visible and "[[" not in visible
    assert len(lookup.calls) == 1 and len(llm.calls) == 3
    assert agent.token_metadata()["total_tokens"] == 36


@pytest.mark.anyio
async def test_smalltalk_keeps_one_model_call():
    llm = ReplayLLM([response("Приветик.", False)])
    lookup = Lookup()
    agent = CharacterAgent(llm, History(), 12, situational_coordinator=Environment(lookup))
    assert await answer(agent, "привет", False) == "Приветик."
    assert len(llm.calls) == 1 and not lookup.calls


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_iris_chooses_topic_without_separate_keyword_planner(live):
    llm = ReplayLLM([command(CALL, live), response("Сама выбрала тему и проверила.", live)])
    lookup = Lookup()
    agent = CharacterAgent(llm, History(), 12, situational_coordinator=Environment(lookup))
    visible = await answer(agent, "вот сама придумай вот что нибудь найди", live)
    assert "Сама выбрала" in visible and len(lookup.calls) == 1 and len(llm.calls) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_promise_after_skill_result_is_repaired_without_second_execution(live):
    llm = ReplayLLM([command(CALL, live), response("Сейчас гляну.", live), response("Результат получен.", live)])
    lookup = Lookup()
    agent = CharacterAgent(llm, History(CONTEXT), 12, situational_coordinator=Environment(lookup))
    visible = await answer(agent, QUESTION, live)
    assert "Результат получен" in visible and "Сейчас гляну" not in visible
    assert len(lookup.calls) == 1 and len(llm.calls) == 3
    assert agent.token_metadata()["total_tokens"] == 36


class LocalArguments(BaseModel):
    topic: str


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_second_registered_skill_uses_same_dialogue_runtime(live):
    calls = []
    async def handler(args):
        calls.append(args.topic)
        return {"value": "локальный факт"}
    skill = Skill("local_reference", "Локальная справка", LocalArguments, handler, lambda: True)
    call = {"name": skill.name, "arguments": {"topic": "навыки"}}
    llm = ChunkedLLM([command(call, live), response("Справка готова.", live)], 3)
    agent = CharacterAgent(llm, History(), 12, skills=(skill,))
    assert "Справка готова" in await answer(agent, "объясни эту возможность", live)
    assert calls == ["навыки"] and len(llm.calls) == 2
    assert any("локальный факт" in m.content for m in llm.calls[1])


@pytest.mark.anyio
@pytest.mark.parametrize("call", [None, SkillCall(name="unknown", arguments={}),
    SkillCall(name="web_search", arguments={"query": "public", "shell": "anything"}),
    SkillCall(name="web_search", arguments={"query": "token sk-secret", "preferred_domains": ["invalid"]})])
async def test_invalid_calls_never_reach_search(call):
    lookup = Lookup()
    agent = CharacterAgent(ReplayLLM([]), History(), 10, situational_coordinator=Environment(lookup))
    result = await agent._perform_skill(call)
    assert result.status != "ok" and not lookup.calls


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_internet_prohibition_cannot_be_overridden_by_model(live):
    llm = ReplayLLM([command(CALL, live), response("Отвечу без проверки в интернете.", live)])
    lookup = Lookup()
    agent = CharacterAgent(llm, History(), 10, situational_coordinator=Environment(lookup))
    assert "без проверки" in await answer(agent, "без интернета расскажи про дата центр", live)
    assert not lookup.calls
    assert any('"status": "disabled"' in m.content for m in llm.calls[1])


@pytest.mark.anyio
async def test_timeout_and_cancellation_close_handler_and_turn_has_one_operation():
    closed = asyncio.Event()
    async def slow(args):
        try:
            await asyncio.sleep(60)
        finally:
            closed.set()
    skill = Skill("local_reference", "test", LocalArguments, slow, lambda: True, timeout_seconds=.01)
    registry = SkillRegistry()
    registry.register(skill)
    call = SkillCall(name=skill.name, arguments={"topic": "x"})
    assert (await registry.execute(call)).status == "timeout" and closed.is_set()
    closed.clear()
    task = asyncio.create_task(registry.execute(call))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    agent = CharacterAgent(ReplayLLM([]), History(), 10, skills=(skill,))
    await agent._perform_skill(call)
    assert (await agent._perform_skill(call)).status == "limit"


@pytest.mark.parametrize("text,live", [("[[skill: broken]]", True), ('{"skill":{"name":"web_search"}}', False)])
def test_malformed_command_stays_internal(text, live):
    assert parse_skill(text, live=live) == (True, None)
