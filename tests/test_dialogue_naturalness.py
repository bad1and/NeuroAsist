"""Turn-level regressions for the reported conversation, not canned replies."""
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.dialogue_pacing import infer_dialogue_pacing
from apps.backend.app.agents.character.dialogue_style import DialogueStyleService
from apps.backend.app.agents.character.search_intent import plan_search, needs_query_planner, search_requested
from apps.backend.app.agents.character.turn_intent import analyze_dialogue_turn, recent_reply_cue
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore, TimelineHistoryAdapter
from tests.test_search_recovery import ReplayLLM, Lookup, Environment, History


@pytest.fixture
def anyio_backend():
    return "asyncio"


def dialogue(answer="По сводке сообщают о 559 беспилотниках за ночь."):
    return [ChatMessage(role="user", content="поищи сводку беспилотников над Россией сегодня"),
            ChatMessage(role="assistant", content=answer)]


@pytest.mark.parametrize("text", ["да", "ага", "угу", "давай", "пу пу пу", "пу-пу-пу",
                                    "но я и говорю что это пиздец какойто", "Ирис приветик"])
def test_reactions_and_greetings_do_not_inherit_completed_lookup(text):
    context = dialogue()
    assert analyze_dialogue_turn(text, context).suppress_lookup
    assert infer_dialogue_pacing(text, context).mode == "micro"
    assert plan_search(text, context) is None
    assert not needs_query_planner(text, context)
    assert not search_requested(text, context)


@pytest.mark.parametrize("text,mode", [
    ("Почему такое количество?", "focused"),
    ("Да, а сколько их сбили сегодня?", "focused"),
    ("Я сказал: найди статистику за неделю", "focused"),
    ("Я имел в виду Тулу", "micro"),
    ("Я имел в виду за вчера", "focused"),
    ("Это жесть, а что произошло?", "focused"),
    ("Я думаю что это работает", "conversational"),
    ("Подробно объясни, как работает память", "deep"),
])
def test_task_and_embedded_conjunction_are_distinguished(text, mode):
    assert infer_dialogue_pacing(text, dialogue()).mode == mode


@pytest.mark.parametrize("offer,accepted", [
    ("Хочешь, проверю свежую сводку?", True),
    ("Могу поискать подробнее про беспилотники.", True),
    ("Проверить ещё раз?", True),
    ("Проверила: ночью сбили 559 беспилотников.", False),
    ("Поискать за сегодня или статистику за неделю?", False),
    ("Хочешь, проверю этот код?", False),
])
def test_agreement_requires_adjacent_unambiguous_offer(offer, accepted):
    context = dialogue(offer)
    assert analyze_dialogue_turn("да", context).accepts_lookup is accepted
    assert (plan_search("да", context) is not None) is accepted
    assert not analyze_dialogue_turn("да", context + [ChatMessage(role="user", content="сменим тему")]).accepts_lookup


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_reported_reaction_sequence_uses_one_generation_and_no_retrieval(tmp_path, live):
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    for m in dialogue():
        store.append_message(role=m.role, content=m.content, input_mode="text", session_id="s",
                             metadata={"web_search": {"query": "сводка беспилотников сегодня", "status": "ok"}} if m.role == "assistant" else None)
    lookup = Lookup()
    inputs = ["да", "пу пу пу", "но я и говорю что это пиздец какойто"]
    replies = ["Ага.", "Мда.", "Да, жесть."]
    provider = ReplayLLM(replies if live else [json.dumps({"reply": r, "emotion": "neutral", "intent": "casual_chat"}, ensure_ascii=False) for r in replies])
    for user_text, reply in zip(inputs, replies):
        agent = CharacterAgent(provider, TimelineHistoryAdapter(store), 10,
                               dialogue_style_service=DialogueStyleService(store),
                               situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
        if live:
            result = "".join([d async for d in agent.stream_user_message("s", user_text)])
        else:
            result = (await agent.handle_user_message("s", user_text))["reply"]
        assert result == reply
        assert agent.last_web_search_metadata is None
        assert agent._search_service_calls == 0
    assert len(provider.calls) == 3 and not lookup.calls
    assert [m.content for m in TimelineHistoryAdapter(store).get_recent_messages("s", 6) if m.role == "assistant"] == replies
    assert all(any("Последние ответы — данные" in m.content for m in batch) for batch in provider.calls)


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_disallowed_model_search_command_is_hidden_without_tool_call(live):
    replies = ["[[web_search: сводка беспилотников]]", "Ага."] if live else ['{"web_search":{"query":"сводка беспилотников"}}', '{"reply":"Ага.","emotion":"neutral","intent":"casual_chat"}']
    provider, lookup = ReplayLLM(replies), Lookup()
    agent = CharacterAgent(provider, History(dialogue()), 10,
                           situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
    if live:
        result = "".join([d async for d in agent.stream_user_message("s", "да", persist_reply=False)])
    else:
        result = (await agent.handle_user_message("s", "да", persist_reply=False))["reply"]
    assert result == "Ага."
    assert not lookup.calls and agent.last_web_search_metadata is None
    assert len(provider.calls) == 2  # Only a protocol violation needs repair.


def test_last_three_replies_are_bounded_untrusted_context():
    context = [ChatMessage(role="assistant", content="older secret marker")]
    context += [ChatMessage(role="assistant", content="[[avatar emotion=neutral]]" + "X" * 300 + tail)
                for tail in ("конвейер", "сводка погоды", "сериал")]
    cue = recent_reply_cue(context)
    assert "older secret marker" not in cue and "[[avatar" not in cue
    assert all(tail in cue for tail in ("конвейер", "сводка погоды", "сериал"))
    assert len(cue) < 1000


@pytest.mark.anyio
@pytest.mark.parametrize("detail", ["давай за сегодня", "а за вчера", "точнее за вчера"])
async def test_date_detail_keeps_topic_and_explicit_time_window(detail):
    agent = CharacterAgent(ReplayLLM([]), History(), 10,
                           situational_coordinator=Environment(Lookup()), runtime_settings=RuntimeSettings())
    request = await agent._plan_turn_search("s", detail, dialogue())
    assert request and "беспилотник" in request.query
    assert request.mode == "news"
    assert datetime.fromisoformat(request.since) < datetime.fromisoformat(request.until)


@pytest.mark.anyio
async def test_absolute_date_from_query_planner_preserves_today_window():
    provider = ReplayLLM(['{"query":"сводка беспилотников 4 октября 2026"}'])
    agent = CharacterAgent(provider, History(), 10,
                           situational_coordinator=Environment(Lookup()), runtime_settings=RuntimeSettings())
    request = await agent._plan_turn_search("s", "поищи про них за сегодня", [])
    assert request.mode == "news" and request.since and request.until
    assert "json" in provider.calls[0][0].content.lower()


@pytest.mark.anyio
async def test_cancel_before_wait_ack_cancels_lookup_without_speech(monkeypatch):
    monkeypatch.setattr("apps.backend.app.agents.character.agent._SEARCH_ACK_DELAY_SECONDS", .1)
    started, cancelled = asyncio.Event(), asyncio.Event()

    class SlowLookup(Lookup):
        async def search(self, *_args, **_kwargs):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

    provider = ReplayLLM([])
    agent = CharacterAgent(provider, History(), 10,
                           situational_coordinator=Environment(SlowLookup()), runtime_settings=RuntimeSettings())
    stream = agent.stream_user_message("s", "Когда выйдет гта шесть?", persist_reply=False)
    first = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await asyncio.wait_for(cancelled.wait(), 1)
    assert not provider.calls and not agent._search_acknowledged


@pytest.mark.anyio
async def test_closing_at_wait_ack_cancels_lookup(monkeypatch):
    monkeypatch.setattr("apps.backend.app.agents.character.agent._SEARCH_ACK_DELAY_SECONDS", .01)
    cancelled = asyncio.Event()

    async def lookup():
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    agent = CharacterAgent(ReplayLLM([]), History(), 10)
    waiting = agent._wait_for_lookup(lookup(), acknowledge=True)
    acknowledgement, _ = await anext(waiting)
    assert acknowledgement and agent._search_acknowledged
    await waiting.aclose()
    assert cancelled.is_set()


@pytest.mark.anyio
async def test_cached_lookup_assessment_does_not_emit_wait_ack(monkeypatch):
    monkeypatch.setattr("apps.backend.app.agents.character.agent._SEARCH_ACK_DELAY_SECONDS", .01)
    agent = CharacterAgent(ReplayLLM([]), History(), 10)

    async def cached_assessment():
        agent._lookup_cached = True
        await asyncio.sleep(.02)
        return "cached evidence"

    parts = [part async for part in agent._wait_for_lookup(cached_assessment(), acknowledge=True)]
    assert parts == [("", "cached evidence")]
    assert not agent._search_acknowledged


@pytest.mark.anyio
async def test_news_word_in_reaction_does_not_trigger_real_coordinator():
    from apps.backend.app.environment.coordinator import SituationalCoordinator
    news, search = AsyncMock(), AsyncMock()
    coordinator = SituationalCoordinator(news_service=news, search_service=search,
                                        location_service=AsyncMock(), weather_service=AsyncMock())
    news.reset_mock()
    search.reset_mock()
    provider = ReplayLLM(["Ага."])
    agent = CharacterAgent(provider, History(dialogue()), 10, situational_coordinator=coordinator,
                           runtime_settings=RuntimeSettings(weather_enabled=False, location_mode="off"))
    try:
        output = "".join([part async for part in agent.stream_user_message("s", "ну сводка вообще пиздец", persist_reply=False)])
        assert output == "Ага."
        assert not news.mock_calls and not search.mock_calls
    finally:
        await coordinator.close()


@pytest.mark.anyio
async def test_actual_duplicate_with_avatar_tags_is_still_rejected():
    previous = "Этот чай лучше заваривать водой чуть холоднее кипятка. Иначе его вкус быстро становится горьким."
    provider = ReplayLLM(["[[avatar emotion=neutral gesture=none]]" + previous, "Да."])
    agent = CharacterAgent(provider, History(dialogue(previous)), 10)
    output = "".join([part async for part in agent.stream_user_message("s", "ага", persist_reply=False)])
    assert output == "Да." and len(provider.calls) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_search_promise_on_reaction_is_repaired_without_lookup(live):
    replies = ["Ща гляну.", "Ага."]
    if not live:
        replies = [json.dumps({"reply": r, "emotion": "neutral", "intent": "casual_chat"}, ensure_ascii=False) for r in replies]
    provider, lookup = ReplayLLM(replies), Lookup()
    agent = CharacterAgent(provider, History(dialogue()), 10, situational_coordinator=Environment(lookup),
                           runtime_settings=RuntimeSettings())
    if live:
        output = "".join([part async for part in agent.stream_user_message("s", "да", persist_reply=False)])
    else:
        output = (await agent.handle_user_message("s", "да", persist_reply=False))["reply"]
    assert output == "Ага." and not lookup.calls and agent.last_web_search_metadata is None
