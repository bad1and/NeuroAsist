import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.search_intent import plan_search
from apps.backend.app.llm.base import ChatMessage
from tests.test_search_conversation_flow import History, ReplayLLM
from tests.test_search_recovery import Environment, Lookup


@pytest.mark.anyio
@pytest.mark.parametrize("size", [1, 3, 17, 1000])
async def test_spoken_search_opening_is_not_delivered_twice(size):
    agent = CharacterAgent(ReplayLLM([]), History(), 10)
    agent._search_bridge_spoken = "Опять про эти дата-центры, да?"
    repeated = "Опять про эти дата-центры, да? Ну вот, теперь нашлось."
    async def stream():
        for index in range(0, len(repeated), size):
            yield repeated[index:index + size]
    continuation = "".join([piece async for piece in agent._without_repeated_search_bridge(stream())])
    assert continuation.strip() == "Ну вот, теперь нашлось."


@pytest.mark.anyio
async def test_similar_but_distinct_continuation_is_preserved():
    agent = CharacterAgent(ReplayLLM([]), History(), 10)
    agent._search_bridge_spoken = "Опять про эти дата-центры, да?"
    text = "Опять про эти данные ничего свежего нет."
    async def stream():
        for letter in text:
            yield letter
    assert "".join([piece async for piece in agent._without_repeated_search_bridge(stream())]) == text


def test_spoken_topic_and_retries_keep_company_and_subject():
    history = []
    for text in ["а че там у нас получается с дата центром яндекса какие там свежие новости по нему",
                 "ну поищи че там с дата центрами их", "еще раз"]:
        request = plan_search(text, history)
        assert request is not None
        assert "яндекс" in request.query and "дата-центры" in request.query
        assert "получается" not in request.query and "их" not in request.query.split()
        history.append(ChatMessage(role="user", content=text))
    assert request.force_refresh


def test_new_topic_replaces_previous_topic_and_retains_region():
    history = [ChatMessage(role="user", content="поищи Яндекс дата центры")]
    request = plan_search("поищи свежие новости Microsoft в России", history)
    assert request and "microsoft" in request.query.casefold() and "россии" in request.query.casefold()
    assert "яндекс" not in request.query


def test_current_information_is_not_limited_to_product_allowlist():
    request = plan_search("какие свежие новости о Nvidia")
    assert request and "nvidia" in request.query.casefold() and request.mode == "news"


@pytest.mark.anyio
async def test_named_news_does_not_use_general_digest():
    agent = CharacterAgent(ReplayLLM([]), History(), 10, situational_coordinator=Environment(Lookup()))
    request = await agent._plan_turn_search("s", "какие свежие новости о Nvidia", [])
    assert request and "nvidia" in request.query.casefold()
    assert agent._news_request_text is None


@pytest.mark.anyio
async def test_search_followup_filters_duplicate_before_delivering_visible_stream(monkeypatch):
    agent = CharacterAgent(ReplayLLM([]), History(), 10)
    agent._search_bridge_spoken = "Опять про серверные? Ну давай глянем, что там стряслось."
    async def generated(*args, **kwargs):
        for letter in agent._search_bridge_spoken + " Свежих данных нет.":
            yield letter
    monkeypatch.setattr(agent, "_guarded_live_stream", generated)
    text = "".join([piece async for piece in agent._live_stream_after_search([], {})])
    assert text.strip() == "Свежих данных нет."
