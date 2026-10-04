"""The reported world-news dialogue must finish retrieval in the same turn."""
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.environment.coordinator import SituationalCoordinator
from apps.backend.app.environment.news_intent import news_request_text
from apps.backend.app.environment.news_service import NewsArticle, NewsDigestSnapshot
from apps.backend.app.runtime.settings import RuntimeSettings
from tests.test_search_recovery import History, ReplayLLM, messages


@pytest.fixture
def anyio_backend():
    return "asyncio"


PROMISE = 'Ну ты и формулировочку выдал — «этот чё там в мире». Ща гляну, чё за движуха.'
ANSWER = "В свежей подборке — запуск научного спутника и открытие выставки."
DIALOGUE = messages("люсь привет", "стт распознал вместо Ирис люсь", "ну да",
                    "че там как у тебя дела", "недавно проснулся", "ночью тебя кодировал",
                    "да кучу разных")


class ChunkedReplayLLM(ReplayLLM):
    async def stream(self, messages):
        response = await self.generate(messages)
        for start in range(0, len(response.content), 7):
            yield response.content[start:start + 7]


def setup_news(replies, *, context=(), empty=False):
    llm = ChunkedReplayLLM(replies)
    news, search = AsyncMock(), AsyncMock()
    today = datetime.now().astimezone().isoformat()
    articles = () if empty else (
        NewsArticle("Запущен научный спутник", "fixture", "Спутник исследует космос", today,
                    "science", "https://example.com/satellite"),
        NewsArticle("Открылась новая выставка", "fixture", "Выставка открылась сегодня", today,
                    "general", "https://example.com/exhibition"),
    )
    news.get_news.return_value = NewsDigestSnapshot("all", articles, 0, updated_at=today)
    coordinator = SituationalCoordinator(news_service=news, search_service=search)
    coordinator.get_ambient_header = AsyncMock(return_value="")
    events = []
    agent = CharacterAgent(llm, History(context), 16, situational_coordinator=coordinator,
                           event_publisher=lambda *event: events.append(event),
                           runtime_settings=RuntimeSettings(weather_enabled=False))
    return agent, news, search, llm, events


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("question,context", [
    ("ну короче этот че там в мире происходит", DIALOGUE),
    ("чё там в мире", DIALOGUE),
    ("происходит", [*DIALOGUE, *messages("ну короче этот че там в мире")]),
    ("что сейчас происходит в мире", DIALOGUE),
    ("здорово ирис че там за движуха в мире", DIALOGUE),
    ("Ирис, какая сегодня движуха в мире?", DIALOGUE),
    ("расскажи, что творится на планете", DIALOGUE),
    ("чем сейчас живёт мир", DIALOGUE),
    ("какие главные события в мире", DIALOGUE),
])
async def test_news_then_answer_repair_without_retrieval_repeat(live, question, context):
    replies = [PROMISE, ANSWER]
    if not live:
        replies = [json.dumps({"reply": reply, "emotion": "neutral", "intent": "question"})
                   for reply in replies]
    agent, news, search, llm, events = setup_news(replies, context=context)
    if live:
        chunks = [c async for c in agent.stream_user_message("session", question,
                   input_mode="voice", persist_reply=False)]
        answer = "".join(chunks)
        assert all("Ща гляну" not in chunk and "формулировочку" not in chunk for chunk in chunks)
    else:
        answer = (await agent.handle_user_message("session", question, persist_reply=False))["reply"]
    assert ANSWER in answer and "Ща гляну" not in answer
    assert news.get_news.await_count == 1
    search.search.assert_not_awaited()
    assert len(llm.calls) == 2 and agent.token_metadata()["total_tokens"] == 24
    assert agent.last_news_metadata["status"] == "ok"
    for call in llm.calls:
        assert any("Запущен научный спутник" in m.content for m in call)
    phases = [e[-1]["phase"] for e in events if e[0] == "retrieval.progress"]
    assert phases == ["searching", "finished"]
    assert agent._retrieval_deadline is not None


@pytest.mark.parametrize("text", ["че там как у тебя дела", "я недавно проснулся", "ну да", "привет", "происходит"])
def test_casual_conversation_does_not_inherit_news(text):
    assert news_request_text(text, messages("чё там в мире", "я только проснулся")) is None


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_direct_news_answer_uses_one_generation_and_keeps_rss_facts(live):
    reply = "Проверила по свежим новостям. " + ANSWER
    responses = [reply if live else json.dumps({"reply": reply, "emotion": "neutral", "intent": "question"})]
    agent, news, search, llm, _ = setup_news(responses, context=DIALOGUE)
    if live:
        answer = "".join([c async for c in agent.stream_user_message("s", "здорово ирис че там за движуха в мире", persist_reply=False)])
    else:
        answer = (await agent.handle_user_message("s", "здорово ирис че там за движуха в мире", persist_reply=False))["reply"]
    assert ANSWER in answer and "Проверила по свежим" in answer
    assert len(llm.calls) == news.get_news.await_count == 1
    search.search.assert_not_awaited()
    # RSS evidence is not permission to invent a Google search or two attempts.
    assert agent._truthful_search_reply("Я гуглила дважды.") != "Я гуглила дважды."


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("second", [ANSWER, "Ни одной внятной новости не вытащила, конкретики ноль."])
async def test_nonempty_rss_digest_cannot_be_replaced_by_global_no_news_claim(live, second):
    replies = ["Ни одной внятной новости не вытащила, конкретики ноль.", second]
    if not live:
        replies = [json.dumps({"reply": r, "emotion": "neutral", "intent": "question"}) for r in replies]
    agent, news, search, llm, _ = setup_news(replies)
    question = "здорово ирис че там за движуха в мире"
    if live:
        answer = "".join([c async for c in agent.stream_user_message("s", question, persist_reply=False)])
    else:
        answer = (await agent.handle_user_message("s", question, persist_reply=False))["reply"]
    assert "Ни одной" not in answer and "конкретики ноль" not in answer
    assert ANSWER in answer or "Запущен научный спутник" in answer
    assert len(llm.calls) == 2 and news.get_news.await_count == 1
    search.search.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_empty_news_and_repeated_promise_finish_honestly(live):
    replies = [PROMISE, "Ща гляну."]
    if not live:
        replies = [json.dumps({"reply": r, "emotion": "neutral", "intent": "question"}) for r in replies]
    agent, news, search, llm, _ = setup_news(replies, empty=True)
    if live:
        answer = "".join([c async for c in agent.stream_user_message("s", "че там в мире", persist_reply=False)])
    else:
        answer = (await agent.handle_user_message("s", "че там в мире", persist_reply=False))["reply"]
    assert "подходящих данных" in answer and "Ща" not in answer
    assert news.get_news.await_count == 1 and len(llm.calls) == 2
    search.search.assert_not_awaited()


@pytest.mark.anyio
async def test_news_disabled_and_no_internet_do_not_refresh_sources():
    agent, news, search, _, _ = setup_news([])
    agent._runtime_settings.news_enabled = False
    await agent._plan_turn_search("s", "че там в мире", [])
    await agent._resolve_turn_context("че там в мире", None, live=False)
    news.get_news.assert_not_awaited()
    agent._runtime_settings.news_enabled = True
    text = "не ищи в интернете, че там в мире"
    await agent._plan_turn_search("s", text, [])
    await agent._resolve_turn_context(text, None, live=False)
    assert news.get_news.await_args.kwargs["refresh"] is False
    search.search.assert_not_awaited()


@pytest.mark.anyio
async def test_news_cancel_clears_progress():
    agent, news, _, _, events = setup_news([])
    entered = asyncio.Event()
    async def wait_for_news(**kwargs):
        entered.set()
        await asyncio.Event().wait()
    news.get_news.side_effect = wait_for_news
    await agent._plan_turn_search("s", "че там в мире", [])
    task = asyncio.create_task(agent._resolve_turn_context("че там в мире", None, live=True))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    phases = [e[-1]["phase"] for e in events if e[0] == "retrieval.progress"]
    assert phases == ["searching", "finished"]


def test_actual_facts_followed_by_promise_are_not_discarded():
    assert not CharacterAgent._search_promise_only(ANSWER + " Ща гляну ещё.")
    assert CharacterAgent._search_promise_only(PROMISE)
