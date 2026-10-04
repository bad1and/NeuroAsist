"""The real RSS → clarification failure, without network or production state."""
import json
import time
from unittest.mock import AsyncMock

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.news_followup import select_news_reference
from apps.backend.app.agents.character.turn_intent import analyze_dialogue_turn
from apps.backend.app.environment.coordinator import _news_topic
from apps.backend.app.environment.news_service import NewsArticle, NewsDigestSnapshot
from apps.backend.app.environment.search_service import SearchService, SearchTurnBudget
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore, TimelineHistoryAdapter
from tests.test_search_recovery import ReplayLLM, Environment


@pytest.fixture
def anyio_backend():
    return "asyncio"


TITLE = "За сутки в российском регионе произошло десять землетрясений"
URL = "https://example.com/news/earthquakes"
ANSWER = "Трамп решает вопрос санкций на нефть. А ещё в одном регионе за сутки десять землетрясений подряд."


def news_metadata():
    return NewsDigestSnapshot("all", (
        NewsArticle(TITLE, "Лента", "На Камчатке зарегистрировали десять землетрясений за сутки.", "2026-10-04", "general", URL),
        NewsArticle("США примут решение по санкциям на нефть", "Газета", "Обсуждаются санкции.", "2026-10-04", "general", "https://example.com/news/sanctions"),
    ), time.time()).metadata()


def history(tmp_path):
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    store.append_message(role="user", content="кстати че там по новостям", session_id="s", input_mode="text")
    store.append_message(role="assistant", content=ANSWER, session_id="s", input_mode="text", metadata={"news": news_metadata()})
    return store, TimelineHistoryAdapter(store)


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
async def test_region_clarification_reads_original_article_and_answers_same_turn(tmp_path, monkeypatch, live, legacy):
    store, adapter = history(tmp_path)
    if legacy:
        reference = adapter.get_recent_news_reference("s")
        for source in reference["news"]["sources"]:
            source.pop("summary", None)
        store.append_message(role="assistant", content=ANSWER, session_id="s", input_mode="text", metadata={"news": reference["news"]})
    page_requests = []
    async def page(_client, url):
        page_requests.append(url)
        return ('<article><h1>' + TITLE + '</h1><p>На Камчатке за сутки произошло десять землетрясений.</p></article>').encode()
    monkeypatch.setattr("apps.backend.app.environment.search_service._read_public_page", page)
    service = SearchService()
    service.search = AsyncMock(side_effect=AssertionError("Should read the existing article, not search for another story"))
    replies = ['{"enough":true,"source_ids":["S1"]}', "На Камчатке."]
    if not live:
        replies[-1] = json.dumps({"reply": replies[-1], "emotion": "neutral", "intent": "question"}, ensure_ascii=False)
    llm = ReplayLLM(replies)
    agent = CharacterAgent(llm, adapter, 10, situational_coordinator=Environment(service), runtime_settings=RuntimeSettings())
    try:
        result = "".join([d async for d in agent.stream_user_message("s", "а в каком регионе", persist_reply=False)]) if live else (await agent.handle_user_message("s", "а в каком регионе", persist_reply=False))["reply"]
        assert result == "На Камчатке."
        assert page_requests == [URL] and not service.search.called
        assert agent.last_web_search_metadata["reason"] == "news_detail"
        assert agent.last_web_search_metadata["budget"]["pages"] == 1
        assert "Камчатке" in " ".join(m.content for m in llm.calls[-1])
        # The chat/voice route owns metadata persistence, as in production.
        store.append_message(role="assistant", content=result, session_id="s", input_mode="text",
                             metadata={"news": agent.last_news_metadata, "web_search": agent.last_web_search_metadata})
        assert adapter.get_recent_retrieval_state("s")["news"]["sources"][0]["url"] == URL
    finally:
        await service.close()


@pytest.mark.anyio
async def test_followup_recovers_source_after_failed_clarification_without_iris_in_query(tmp_path):
    store, adapter = history(tmp_path)
    store.append_message(role="user", content="а в каком регионе", session_id="s", input_mode="text")
    store.append_message(role="assistant", content="Не помню точно. Сейчас гляну.", session_id="s", input_mode="text")
    agent = CharacterAgent(ReplayLLM([]), adapter, 10, situational_coordinator=Environment(SearchService()), runtime_settings=RuntimeSettings())
    request = await agent._plan_turn_search("s", "так можешь пожалуйста поискать ирис", adapter.get_recent_messages("s", 10))
    assert request and request.reason == "news_detail" and TITLE in request.query
    assert "ирис" not in request.query.casefold()


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_internet_forbidden_uses_saved_news_summary_without_lookup(tmp_path, live):
    _, adapter = history(tmp_path)
    service = SearchService()
    service.search = AsyncMock(side_effect=AssertionError("Internet forbidden"))
    service.read_sources = AsyncMock(side_effect=AssertionError("Internet forbidden"))
    reply = "В полученной подборке указана Камчатка."
    llm = ReplayLLM([reply if live else json.dumps({"reply": reply, "emotion": "neutral", "intent": "question"}, ensure_ascii=False)])
    agent = CharacterAgent(llm, adapter, 10, situational_coordinator=Environment(service), runtime_settings=RuntimeSettings())
    text = "а в каком регионе, без интернета"
    result = "".join([d async for d in agent.stream_user_message("s", text)]) if live else (await agent.handle_user_message("s", text))["reply"]
    assert result == reply
    assert "Камчатке" in " ".join(m.content for m in llm.calls[0])
    assert not service.search.called and not service.read_sources.called


def test_ambiguous_detail_or_new_subject_cannot_select_a_random_story():
    messages = [ChatMessage(role="assistant", content=ANSWER)]
    reference = {"news": news_metadata(), "reply": ANSWER}
    assert select_news_reference("а в каком регионе", messages, reference)[0]["url"] == URL
    assert not select_news_reference("а когда", messages, reference)
    assert not select_news_reference("где купить ноутбук", messages, reference)
    changed = [*messages, ChatMessage(role="user", content="кстати новости Питера"), ChatMessage(role="assistant", content="Сменили тему.")]
    assert not select_news_reference("а в каком регионе", changed, reference)


def test_local_news_topic_and_colloquial_search_offer():
    assert _news_topic("ну че там допустим в питере по новостям") == "Санкт-Петербург"
    assert _news_topic("новости в Питере за сегодня") == "Санкт-Петербург"
    assert analyze_dialogue_turn("давай", [ChatMessage(role="assistant", content="Если хочешь, могу отдельно глянуть именно по городу.")]).accepts_lookup


@pytest.mark.parametrize("reply", [
    "Не помню точно, я ж тебе по памяти не назову, а врать не хочу. Сейчас гляну. Вот, значит, я в прошлый раз сказала не проверив — и это моя косяк, извини.",
    "Не знаю точно. Сейчас проверю.",
])
def test_uncertainty_and_apology_do_not_disguise_an_unfulfilled_promise(reply):
    assert CharacterAgent._search_promise_only(reply)
    assert not CharacterAgent._search_promise_only("На Камчатке было десять землетрясений за сутки.")


@pytest.mark.anyio
async def test_read_sources_respects_existing_page_budget():
    from apps.backend.app.environment.search_service import SearchResult
    service = SearchService()
    service._page = AsyncMock(side_effect=AssertionError("Budget exhausted"))
    budget = SearchTurnBudget(time.monotonic() + 5, pages=3)
    result = await service.read_sources(TITLE, [SearchResult(TITLE, "", URL)], budget=budget)
    assert not service._page.called and not result.results


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_observed_nonanswer_is_repaired_against_selected_article(tmp_path, live):
    _, adapter = history(tmp_path)
    service = SearchService()
    async def page(result, query):
        from dataclasses import replace
        return replace(result, page_text="На Камчатке за сутки произошло десять землетрясений.", page_status="read")
    service._page = page
    service.search = AsyncMock(side_effect=AssertionError("Repeated lookup"))
    promise = "Не помню точно, я ж тебе по памяти не назову, а врать не хочу. Сейчас гляну. Вот, значит, я в прошлый раз сказала не проверив — и это моя косяк, извини."
    replies = [promise, "На Камчатке."]
    if not live:
        replies = [json.dumps({"reply": r, "emotion": "neutral", "intent": "question"}, ensure_ascii=False) for r in replies]
    llm = ReplayLLM(['{"enough":true,"source_ids":["S1"]}', *replies])
    agent = CharacterAgent(llm, adapter, 10, situational_coordinator=Environment(service), runtime_settings=RuntimeSettings())
    try:
        result = "".join([d async for d in agent.stream_user_message("s", "а в каком регионе", persist_reply=False)]) if live else (await agent.handle_user_message("s", "а в каком регионе", persist_reply=False))["reply"]
        assert result == "На Камчатке." and not service.search.called
        assert len(llm.calls) == 3
        assert "именно на уточнение" in " ".join(m.content for m in llm.calls[-1])
    finally:
        await service.close()


@pytest.mark.anyio
async def test_local_news_offer_acceptance_performs_search_in_same_turn():
    from tests.test_colloquial_news_search import setup_news
    from apps.backend.app.environment.search_service import SearchResult, SearchSnapshot
    context = [ChatMessage(role="user", content="ну че там допустим в питере по новостям"),
               ChatMessage(role="assistant", content="Если хочешь, могу отдельно глянуть именно по городу.")]
    agent, news, search, llm, _ = setup_news(["В Петербурге открылась выставка."], context=context, empty=True)
    search.search.return_value = SearchSnapshot(query="Санкт-Петербург новости", mode="news", results=(
        SearchResult("В Петербурге открылась выставка", "Сегодня открылась выставка", "https://example.com/spb", published_at="2026-10-05"),))
    result = "".join([d async for d in agent.stream_user_message("s", "давай", persist_reply=False)])
    assert "выставка" in result
    assert news.get_news.call_args.kwargs["query"] == "Санкт-Петербург"
    assert search.search.await_count == 1 and "Санкт-Петербург" in search.search.call_args.args[0]
    assert len(llm.calls) == 1
