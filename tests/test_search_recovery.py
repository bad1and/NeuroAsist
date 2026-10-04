"""Regressions from the user's conversation, plus opt-in provider contracts."""
import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from apps.backend import desktop_entry
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.search_intent import plan_search, needs_query_planner
from apps.backend.app.api.routes.environment import get_environment_news
from apps.backend.app.core.config import Settings, get_settings, configure_runtime_credentials
from apps.backend.app.environment.coordinator import SituationalCoordinator
from apps.backend.app.environment.news_service import NewsService, NewsArticle
from apps.backend.app.environment.retrieval import relevance
from apps.backend.app.environment.search_service import SearchService, SearchResult
from apps.backend.app.llm.base import ChatMessage, LLMProvider, LLMResponse, LLMUsage
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
from apps.backend.app.storage.timeline import TimelineStore, TimelineHistoryAdapter


@pytest.fixture
def anyio_backend():
    return "asyncio"


def messages(*texts):
    return [ChatMessage(role="user", content=t) for t in texts]


DEADLOCK = messages("знаешь ли ты такую замечательную игру дыдлок",
                    "какой какой там самый последний перс вышел", "вот прям недавно")


def test_recover_deadlock_fragment_and_yesterday_without_gibberish():
    request = plan_search("поищи выноти", DEADLOCK)
    assert request and "deadlock" in request.query and "герой" in request.query
    assert "выноти" not in request.query and len(request.query) < 100
    later = plan_search("вчера", [*DEADLOCK, *messages("поищи выноти")])
    assert later and "deadlock" in later.query and "вчера" in later.query
    assert plan_search("поищи выноти", [*DEADLOCK, *messages("Привет")]) is None
    assert plan_search("не обращайся ни к чему просто что знаешь про дедлок", DEADLOCK) is None
    today = plan_search("сегодня", [*DEADLOCK, *messages("поищи Deadlock последний новый герой вчера")])
    assert today and "сегодня" in today.query and "вчера" not in today.query


def test_anecdote_correction_keeps_user_fragment_and_never_inherits_game():
    history = messages("найди анекдот доктор у меня провалы в памяти",
                       "нет другой анекдот начинался доктор у меня провал в памяти в чем в памяти давно")
    request = plan_search("можешь поискать прям другой анекдот это не то", history)
    assert request and "доктор" in request.query and "давно" in request.query and request.force_refresh
    assert plan_search("можешь поискать другой анекдот", DEADLOCK) is None
    assert needs_query_planner("можешь поискать другой анекдот", DEADLOCK)
    assert not needs_query_planner("ты тут", [])


def test_modifiers_do_not_become_required_entity_or_year():
    assert relevance("Deadlock latest new hero October 2026", "Deadlock: новый герой Крысиный король") > 0
    assert relevance("Deadlock latest hero", "Overwatch new hero") == 0
    assert relevance("GTA VI new release announcement", "GTA V release date") == 0


def test_actual_noisy_deadlock_request_and_inflections():
    text = "можешь поискать че нибудь допустим вот какой последний персонаж в дедлоке вышел вот давай вернемся к этому вопросу"
    assert plan_search(text).query == "deadlock последний новый герой"
    assert relevance(plan_search(text).query, "Deadlock: новый герой вышел") > 0
    for name in ("дедлока", "дэдлоке", "дыдлоком"):
        assert "deadlock" in plan_search(f"поищи последний персонаж {name}").query


def test_current_election_question_corrections_and_event_year():
    question = "кто победил на выборах в госдуму россии"
    request = plan_search(question)
    assert request and str(datetime.now().astimezone().year) in request.query
    history = messages(question, "але блять ирис", "да сейчас естественно сейчас")
    continued = plan_search("ну и что там", history)
    assert continued and continued.query == request.query
    assert "2026" in plan_search("выборы в госдуму года двадцать шестого блять").query
    assert "2024" in plan_search("кто победил на выборах в госдуму 2024").query
    refreshed = plan_search("да сейчас естественно сейчас", messages("кто победил на выборах в госдуму 2021"))
    assert str(datetime.now().astimezone().year) in refreshed.query and "2021" not in refreshed.query
    assert plan_search("ну и что там", [*history, *messages("расскажи про кошек")]) is None
    assert plan_search("не ищи в интернете кто победил на выборах в госдуму") is None
    assert relevance(request.query, "Выборы в Госдуму 2025 результаты Россия") == 0
    assert relevance(request.query, "Выборы в Госдуму " + str(datetime.now().astimezone().year) + " результаты Россия") > 0
    assert plan_search("кто выиграл чемпионат мира по футболу").query.startswith("чемпионат мира по футболу")


class ReplayLLM(LLMProvider):
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
        self.last_response = None

    async def generate(self, messages):
        self.calls.append(messages)
        self.last_response = LLMResponse(content=next(self.replies), model="fixture",
                                         usage=LLMUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12))
        return self.last_response

    async def stream(self, messages):
        response = await self.generate(messages)
        yield response.content


class History:
    def __init__(self, context=()):
        self.context = list(context)

    def get_recent_messages(self, _session_id, limit):
        return self.context[-limit:] if limit else self.context

    def save_message(self, *args):
        pass


class Lookup:
    def __init__(self):
        self.calls = []

    async def search(self, query, **options):
        self.calls.append((query, options))
        return SearchService._snapshot(query, status="ok", results=[SearchResult(
            "Deadlock: новый герой", "Вышел новый герой игры Deadlock", "https://example.com/deadlock")])


class Environment:
    def __init__(self, lookup):
        self.search_service = lookup

    async def get_ambient_header(self, **kwargs):
        return "[Контекст окружения: тест]"

    async def evaluate_and_enrich(self, *args, **kwargs):
        return None


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_fragment_search_and_answer_complete_in_same_text_or_voice_turn(live):
    llm = ReplayLLM(["Новый герой найден." if live else '{"reply":"Новый герой найден.","emotion":"neutral","intent":"question"}'])
    lookup = Lookup()
    agent = CharacterAgent(llm, History(DEADLOCK), 8, situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
    if live:
        visible = "".join([c async for c in agent.stream_user_message("s", "поищи выноти", input_mode="voice", persist_reply=False)])
        assert visible.count("Так, секунду, проверю") == 1
    else:
        visible = (await agent.handle_user_message("s", "поищи выноти", persist_reply=False))["reply"]
    assert "Новый герой найден" in visible
    assert len(lookup.calls) == len(llm.calls) == 1
    assert "deadlock" in lookup.calls[0][0] and "выноти" not in lookup.calls[0][0]
    assert "https://" not in visible


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_observed_promise_only_reply_is_repaired_without_repeating_lookup(live):
    replies = ["Так, секунду, проверю.", "Результат проверки получен."]
    if not live:
        replies = [json.dumps({"reply": r, "emotion": "neutral", "intent": "question"}) for r in replies]
    llm = ReplayLLM(replies)
    lookup = Lookup()
    agent = CharacterAgent(llm, History(), 8, situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
    text = "кто победил на выборах в госдуму россии"
    if live:
        visible = "".join([c async for c in agent.stream_user_message("s", text, input_mode="voice", persist_reply=False)])
        assert visible.count("Так, секунду, проверю") == 1
    else:
        visible = (await agent.handle_user_message("s", text, persist_reply=False))["reply"]
    assert "Результат проверки получен" in visible
    assert len(lookup.calls) == 1 and len(llm.calls) == 2
    assert agent.token_metadata()["total_tokens"] == 24
    assert agent.last_web_search_metadata["query"] == lookup.calls[0][0]


@pytest.mark.anyio
async def test_repeated_promise_has_bounded_fallback_and_no_false_repeat_search():
    llm = ReplayLLM(["Ща гляну, чё там по свежим.", "Ща."])
    lookup = Lookup()
    agent = CharacterAgent(llm, History(), 8, situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
    visible = "".join([c async for c in agent.stream_user_message("s", "поищи последний герой дедлока", input_mode="voice", persist_reply=False)])
    assert "Ща" not in visible and "Проверка завершена" in visible
    assert len(lookup.calls) == 1 and len(llm.calls) == 2


@pytest.mark.anyio
async def test_outcome_search_continues_past_schedule_and_rejects_wrong_year(monkeypatch):
    query = "выборы Государственная Дума России 2026 итоги результаты"
    calls = []
    service = SearchService()
    async def provider(name, actual_query):
        calls.append((name, actual_query))
        if len(calls) == 1:
            return [SearchResult("Выборы в Госдуму России 2026", "Выборы в Госдуму России 2026 запланированы на сентябрь", "https://example.com/schedule")], "ok"
        if len(calls) == 2:
            return [SearchResult("Выборы в Госдуму России 2025 результаты", "Партия победила на выборах в Госдуму России 2025", "https://example.com/old")], "ok"
        return [SearchResult("Выборы в Госдуму России 2026 итоги", "ЦИК утвердил окончательные итоги: партия победила на выборах в Госдуму России 2026 и получила 300 мандатов", "https://example.com/results")], "ok"
    async def page(result, _query):
        return result
    monkeypatch.setattr(service, "_provider", provider)
    monkeypatch.setattr(service, "_page", page)
    try:
        snap = await service.search(query)
        assert len(calls) == 3 and snap.results[0].url.endswith("/results")
        assert all(not r.url.endswith("/old") for r in snap.results)
        assert snap.metadata()["evidence_status"] == "available"
        assert "расписание" in snap.compact_summary()
    finally:
        await service.close()


@pytest.mark.anyio
async def test_provisional_outcomes_use_reserve_and_never_become_final(monkeypatch):
    service = SearchService()
    calls = []
    async def provider(name, query):
        calls.append(query)
        return [SearchResult("Выборы в Госдуму России 2026 предварительные результаты",
                            "Партия набрала 57% голосов на выборах в Госдуму России 2026 по неполным протоколам",
                            "https://example.com/provisional")], "ok"
    async def page(result, _query):
        return result
    monkeypatch.setattr(service, "_provider", provider)
    monkeypatch.setattr(service, "_page", page)
    try:
        snap = await service.search("выборы Государственная Дума России 2026 итоги результаты")
        assert len(calls) == 3
        assert snap.metadata()["evidence_status"] == "provisional"
        assert "не называй их окончательными" in snap.compact_summary()
    finally:
        await service.close()


def test_sport_translation_and_forecast_are_not_winner_evidence():
    from apps.backend.app.environment.search_service import _outcome_evidence
    assert relevance("чемпионат мира по футболу 2026 победитель финал", "Spain won FIFA World Cup 2026 final") > 0
    assert relevance("чемпионат мира по футболу 2026 победитель финал", "Hockey World Cup 2026 final") == 0
    forecast = SearchResult("Выборы-2026: как может измениться состав Госдумы?", "Партия набрала бы 57% голосов по прогнозу", "https://example.com/forecast")
    assert not _outcome_evidence(forecast)


@pytest.mark.anyio
async def test_yesterday_keeps_entity_and_local_period():
    agent = CharacterAgent(ReplayLLM([]), History(), 8, situational_coordinator=Environment(Lookup()), runtime_settings=RuntimeSettings())
    request = await agent._plan_turn_search("s", "вчера", [*DEADLOCK, *messages("поищи выноти")])
    assert request.mode == "news" and request.since and request.until
    assert datetime.fromisoformat(request.until) - datetime.fromisoformat(request.since) == timedelta(days=1)
    assert datetime.fromisoformat(request.since).hour == 0


@pytest.mark.anyio
@pytest.mark.parametrize("planner", ['{"query":"Deadlock новый герой"}', '{"query":"выноти"}', '{"clarify":true}'])
async def test_ambiguous_planner_is_bounded_counted_and_never_searches_gibberish(planner):
    llm = ReplayLLM([planner, '{"reply":"Уточни предмет поиска.","emotion":"neutral","intent":"question"}'])
    lookup = Lookup()
    agent = CharacterAgent(llm, History(messages("какое то название")), 8, situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
    await agent.handle_user_message("s", "можешь поискать выноти", persist_reply=False)
    assert len(llm.calls) == 2 and len(llm.calls[0][-1].content) <= 2000
    assert agent.token_metadata()["total_tokens"] == 24
    assert bool(lookup.calls) == ("Deadlock" in planner)
    if not lookup.calls:
        assert agent.last_web_search_metadata["status"] == "needs_clarification"
        assert any("Поиск не запускался" in m.content for m in llm.calls[-1])


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["brave", "tavily", "serper"])
@pytest.mark.parametrize("mode", ["web", "news"])
async def test_api_adapters_normalize_formats_and_only_use_selected_service(provider, mode, caplog, monkeypatch):
    from apps.backend.app.environment import search_service as module
    async def public_address(*args):
        return "93.184.216.34"
    monkeypatch.setattr(module, "_public_address", public_address)
    calls = []
    date = datetime.now(UTC).isoformat()
    def handler(request):
        calls.append(request)
        if request.url.host == "93.184.216.34":
            return httpx.Response(200, text="<p>Python documentation and programming docs.</p>")
        item = {"title": "Python documentation", "url": "https://python.org/doc", "link": "https://python.org/doc",
                "description": "Python docs", "content": "Python docs", "snippet": "Python docs", "published_date": date, "page_age": date, "date": date}
        if provider == "brave":
            payload = {"results": [item]} if mode == "news" else {"web": {"results": [item]}}
        elif provider == "tavily":
            payload = {"results": [item]}
        else:
            payload = {"news" if mode == "news" else "organic": [item]}
        return httpx.Response(200, json=payload)
    from apps.backend.app.environment.search_providers import api_search
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await api_search(client, provider, "fixture-secret", "Python documentation", mode=mode)
        assert rows[0]["provider"] == provider and rows[0]["published_at"]
        assert len([r for r in calls if r.url.host != "93.184.216.34"]) == 1
        assert "fixture-secret" not in json.dumps(rows) + caplog.text
        if provider == "tavily":
            assert json.loads(calls[0].content)["include_answer"] is False
            assert json.loads(calls[0].content)["search_depth"] == "basic"


@pytest.mark.anyio
async def test_free_is_default_with_keys_and_force_refresh_bypasses_cache():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == "html.duckduckgo.com"
        return httpx.Response(200, text='<a class="result__a" href="https://python.org">Python docs</a><div class="result__snippet">Python docs</div>')
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), credentials={"brave": "secret"})
    try:
        assert (await service.search("Python docs")).status == "ok"
        assert (await service.search("Python docs")).cached
        assert not (await service.search("Python docs", force_refresh=True)).cached
        assert len(calls) == 2
    finally:
        await service.close()


@pytest.mark.anyio
async def test_paid_failure_uses_free_not_another_paid_service(caplog):
    hosts = []
    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "api.search.brave.com":
            return httpx.Response(401, text="fixture-secret")
        assert request.url.host == "html.duckduckgo.com"
        return httpx.Response(200, text='<a class="result__a" href="https://python.org">Python docs</a><div class="result__snippet">Python docs</div>')
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), runtime_settings=RuntimeSettings(web_search_provider="brave"),
                            credentials={p: "fixture-secret" for p in ("brave", "tavily", "serper")})
    try:
        snap = await service.search("Python docs")
        assert snap.status == "ok" and snap.attempts[0]["provider"] == "duckduckgo"
        assert hosts == ["html.duckduckgo.com"]
        assert "fixture-secret" not in caplog.text + json.dumps(snap.metadata())
    finally:
        await service.close()


@pytest.mark.anyio
async def test_cold_topic_feed_waits_and_continuation_excludes_shown_events(monkeypatch):
    from apps.backend.app.environment import news_service as module
    monkeypatch.setattr(module, "FEEDS", {"games": [("test", "https://example.com/feed")]})
    async def handler(request):
        await asyncio.sleep(.01)
        date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
        return httpx.Response(200, text="<rss><channel>" + "".join(f"<item><title>Deadlock event {i}</title><description>Deadlock</description><pubDate>{date}</pubDate><link>https://example.com/{i}</link></item>" for i in range(22)) + "</channel></rss>")
    service = NewsService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        first = await service.get_news("games", max_articles=7, query="Deadlock")
        assert len(first.articles) == 7 and first.source_health[0]["status"] == "ok"
        second = await service.get_news("games", max_articles=20, query="Deadlock", exclude_urls=first.shown_urls, exclude_titles=first.shown_titles)
        assert len(second.articles) == 15
        assert not {a.url for a in first.articles} & {a.url for a in second.articles}
        assert len(first.compact_summary(max_items=7, max_chars=2800).splitlines()) == 8
    finally:
        await service.close()


@pytest.mark.anyio
async def test_news_cursor_pages_and_rejects_invalid_cursor(monkeypatch):
    from apps.backend.app.environment import news_service as module
    monkeypatch.setattr(module, "FEEDS", {"games": [("test", "https://example.com/feed")]})
    service = NewsService()
    date = datetime.now(UTC).isoformat()
    service._sources["https://example.com/feed"] = (tuple(NewsArticle(f"Story {i}", "test", "", date, "games", f"https://example.com/{i}") for i in range(12)), time.monotonic(), date)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(situational_coordinator=SimpleNamespace(news_service=service), runtime_settings=RuntimeSettings(news_category="games"))))
    try:
        first = await get_environment_news(request, limit=7)
        assert first["next_cursor"] and len(first["articles"]) == 7
        second = await get_environment_news(request, limit=7, cursor=first["next_cursor"])
        assert len(second["articles"]) == 5 and second["next_cursor"] is None
        assert not {a["url"] for a in first["articles"]} & {a["url"] for a in second["articles"]}
        with pytest.raises(HTTPException):
            await get_environment_news(request, cursor="invalid")
    finally:
        await service.close()


@pytest.mark.anyio
async def test_topic_news_preserves_rss_and_supplements_up_to_seven():
    from unittest.mock import AsyncMock
    from apps.backend.app.environment.news_service import NewsDigestSnapshot
    news, search = AsyncMock(), AsyncMock()
    date = datetime.now(UTC).isoformat()
    article = NewsArticle("Deadlock событие 0", "RSS", "Details", date, "games", "https://example.com/0")
    news.get_news.return_value = NewsDigestSnapshot("games", (article,), 0, query="Deadlock",
                                                   shown_urls=(article.url,), shown_titles=(article.title,))
    search.search.return_value = SearchService._snapshot("Deadlock новости", mode="news", status="ok", results=[
        SearchResult(f"Deadlock событие {i}", "Details", f"https://example.com/{i}", published_at=date) for i in range(7)])
    coordinator = SituationalCoordinator(news_service=news, search_service=search)
    result = await coordinator._handle_news_intent("новости про Deadlock", "all")
    assert len(result.news.articles) == 7 and result.news.articles[0] is article
    assert len(result.search.results) == 6
    assert result.news.metadata()["shown_urls"][0] == article.url
    assert "RSS" in result.text and len(result.text) <= 3200
    assert search.search.await_args.kwargs["mode"] == "news"


@pytest.mark.anyio
async def test_agent_reconstructs_news_continuation_from_persisted_session(tmp_path, monkeypatch):
    from apps.backend.app.environment import news_service as module
    monkeypatch.setattr(module, "FEEDS", {"games": [("test", "https://example.com/rss")]})
    service = NewsService()
    date = datetime.now(UTC).isoformat()
    service._sources["https://example.com/rss"] = (tuple(NewsArticle(f"Event {i}", "test", "", date, "games", f"https://example.com/{i}") for i in range(14)), time.monotonic(), date)
    first = await service.get_news("games", max_articles=7, refresh=False)
    store = TimelineStore(tmp_path / "news.sqlite3")
    store.init_db()
    store.append_message(role="assistant", content="Сводка", input_mode="text", session_id="s", metadata={"news": first.metadata()})
    coordinator = SituationalCoordinator(news_service=service)
    agent = CharacterAgent(ReplayLLM([]), TimelineHistoryAdapter(store), 8, situational_coordinator=coordinator,
                           runtime_settings=RuntimeSettings(location_mode="manual", weather_enabled=False))
    try:
        request = await agent._plan_turn_search("s", "давай ещё новости", [])
        assert request is None and agent._news_continuation
        await agent._resolve_turn_context("давай ещё новости", request, live=False)
        second = agent.last_news_metadata
        assert len(second["sources"]) == 7
        assert not set(first.shown_urls) & {a["url"] for a in second["sources"]}
        assert len(second["shown_urls"]) == 14
    finally:
        await coordinator.close()


@pytest.mark.anyio
async def test_period_rechecks_dates_after_page_read_and_shared_deadline_cancels(monkeypatch):
    service = SearchService()
    async def provider(*args):
        return [SearchResult("Deadlock герой", "Deadlock новый герой", "https://example.com/hero")], "ok"
    async def old_page(result, query):
        from dataclasses import replace
        return replace(result, published_at="2025-01-01T00:00:00+00:00", page_status="read")
    monkeypatch.setattr(service, "_provider", provider)
    monkeypatch.setattr(service, "_page", old_page)
    try:
        snap = await service.search("Deadlock новый герой", since="2026-10-02T00:00:00+03:00", until="2026-10-03T00:00:00+03:00")
        assert not snap.results and snap.status == "empty"
        cancelled = asyncio.Event()
        async def slow(*args):
            try:
                await asyncio.sleep(1)
            finally:
                cancelled.set()
        monkeypatch.setattr(service, "_provider", slow)
        start = time.monotonic()
        snap = await service.search("Deadlock другой герой", deadline=start + .03)
        assert snap.status == "timeout" and cancelled.is_set()
        assert time.monotonic() - start < .2
    finally:
        await service.close()


def test_news_state_survives_agent_recreation_but_not_other_session_or_new_topic(tmp_path):
    store = TimelineStore(tmp_path / "history.sqlite3")
    store.init_db()
    state = {"category": "games", "topic": "Deadlock", "shown_urls": ["https://example.com/1"]}
    store.append_message(role="assistant", content="Новость", input_mode="text", metadata={"news": state}, session_id="one")
    adapter = TimelineHistoryAdapter(store)
    assert adapter.get_recent_retrieval_state("one")["news"] == state
    assert adapter.get_recent_retrieval_state("two") == {}
    store.append_message(role="assistant", content="Другая тема", input_mode="text", session_id="one")
    assert adapter.get_recent_retrieval_state("one") == {}


def test_upgrade_defaults_free_and_keys_are_never_external_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 1, "settings": {"news_enabled": True}}))
    assert RuntimeSettingsStore(path).load(RuntimeSettings()).web_search_provider == "free"
    for provider in ("brave", "tavily", "serper"):
        monkeypatch.setenv(f"{provider.upper()}_API_KEY", "ignored")
    settings = Settings(_env_file=None)
    assert all(getattr(settings, f"{p}_api_key") is None for p in ("brave", "tavily", "serper"))


def test_search_keys_use_desktop_pipe_and_remain_independent(monkeypatch):
    monkeypatch.setenv("NEUROASIST_CREDENTIALS_STDIN", "1")
    monkeypatch.setattr(desktop_entry.sys, "stdin", SimpleNamespace(buffer=BytesIO(b'{"brave_api_key":"b","tavily_api_key":"t","serper_api_key":"s"}\n')))
    try:
        desktop_entry.load_runtime_credentials()
        settings = get_settings()
        assert (settings.brave_api_key, settings.tavily_api_key, settings.serper_api_key) == ("b", "t", "s")
        assert settings.llm_api_key is None
    finally:
        configure_runtime_credentials(deepseek_api_key=None, coding_api_key=None)
