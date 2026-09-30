import asyncio

import httpx
import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.environment.search_service import SearchResult, SearchService, SearchSnapshot
from apps.backend.app.llm.base import LLMResponse, LLMUsage
from apps.backend.app.runtime.settings import RuntimeSettings


class History:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []

    def get_recent_messages(self, _session_id: str, limit: int):
        return []

    def save_message(self, session_id: str, role: str, content: str) -> None:
        self.saved.append((session_id, role, content))


class StubSearch:
    def __init__(self, snapshot: SearchSnapshot) -> None:
        self.snapshot = snapshot
        self.queries: list[str] = []

    async def search(self, query: str, **_options) -> SearchSnapshot:
        self.queries.append(query)
        return self.snapshot


class Coordinator:
    def __init__(self, search_service: StubSearch) -> None:
        self.search_service = search_service

    async def get_ambient_header(self, **_kwargs) -> str:
        return "[Контекст окружения: тест]"

    async def evaluate_and_enrich(self, *_args, **_kwargs):
        return None


class SearchProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.last_response = None
        self.last_call_metrics = None
        self.seen_messages = []

    async def generate(self, messages):
        self.seen_messages.append(list(messages))
        content = self.responses[self.calls]
        self.calls += 1
        self.last_response = LLMResponse(
            content=content,
            model="test",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
            latency_ms=20,
        )
        return self.last_response

    async def stream(self, messages):
        self.seen_messages.append(list(messages))
        content = self.responses[self.calls]
        self.calls += 1
        for chunk in (content[:8], content[8:19], content[19:]):
            if chunk:
                yield chunk
        self.last_response = LLMResponse(
            content=content,
            model="test",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
            latency_ms=20,
        )


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_spoken_gta_release_request_searches_before_model_answer(live) -> None:
    answer = "Проверила: релиз объявлен на 19 ноября 2026 года."
    response = answer if live else ('{"reply":"' + answer + '","emotion":"neutral","intent":"question"}')
    provider = SearchProvider([response])
    search = StubSearch(snapshot())
    agent = CharacterAgent(provider, History(), 0,
                           situational_coordinator=Coordinator(search), runtime_settings=RuntimeSettings())
    request = "да вроде починил попробую еще раз найти про гта шесть когда релиз"
    if live:
        visible = "".join([part async for part in agent.stream_user_message("s", request, persist_reply=False)])
    else:
        visible = (await agent.handle_user_message("s", request, persist_reply=False))["reply"]
    assert len(search.queries) == 1
    assert "GTA VI" in search.queries[0]
    assert provider.calls == 1
    assert answer in visible
    assert agent.last_web_search_metadata["status"] == "ok"


def snapshot() -> SearchSnapshot:
    return SearchSnapshot(
        query="актуальная версия Python",
        results=(SearchResult("Python", "Свежая версия языка", "https://python.org/downloads/"),),
        status="ok",
        searched_at="2026-09-28T12:00:00+00:00",
    )


@pytest.mark.anyio
async def test_batch_search_command_is_hidden_and_sources_are_retained() -> None:
    provider = SearchProvider([
        '{"web_search":{"query":"актуальная версия Python"}}',
        '{"reply":"Проверила: версия Python свежая.","emotion":"neutral","intent":"question"}',
    ])
    search = StubSearch(snapshot())
    agent = CharacterAgent(
        provider, History(), 0,
        situational_coordinator=Coordinator(search),
        runtime_settings=RuntimeSettings(web_search_enabled=True),
    )

    result = await agent.handle_user_message("s", "Расскажи про Python", persist_reply=False)

    assert result["reply"] == "Проверила: версия Python свежая."
    assert "web_search" not in result["reply"]
    assert search.queries == ["актуальная версия Python"]
    assert agent.last_web_search_metadata["sources"][0]["url"] == "https://python.org/downloads/"
    assert agent.token_metadata()["total_tokens"] == 24


@pytest.mark.anyio
async def test_live_search_command_split_across_chunks_never_reaches_visible_stream() -> None:
    provider = SearchProvider([
        "[[web_search: актуальная версия Python]]",
        "[[avatar emotion=neutral gesture=auto intensity=1.0]] Сейчас проверила: версия свежая.",
    ])
    search = StubSearch(snapshot())
    agent = CharacterAgent(
        provider, History(), 0,
        situational_coordinator=Coordinator(search),
        runtime_settings=RuntimeSettings(web_search_enabled=True),
    )

    visible = "".join([part async for part in agent.stream_user_message("s", "Проверь Python", persist_reply=False)])

    assert "web_search" not in visible
    assert "Сейчас проверила" in visible
    assert provider.calls == 2
    assert search.queries == ["актуальная версия Python"]


@pytest.mark.anyio
async def test_malformed_live_search_command_is_hidden_and_not_sent_to_provider() -> None:
    provider = SearchProvider([
        "[[web_search query missing separator]]",
        "[[avatar emotion=neutral gesture=auto intensity=1.0]] Не удалось проверить данные.",
    ])
    search = StubSearch(snapshot())
    agent = CharacterAgent(
        provider, History(), 0,
        situational_coordinator=Coordinator(search),
        runtime_settings=RuntimeSettings(web_search_enabled=True),
    )

    visible = "".join([part async for part in agent.stream_user_message("s", "Проверь данные", persist_reply=False)])

    assert "web_search" not in visible
    assert "Не удалось проверить" in visible
    assert search.queries == []
    assert agent.last_web_search_metadata["status"] == "invalid"


@pytest.mark.anyio
async def test_search_service_extracts_real_urls_and_coalesces_concurrent_requests() -> None:
    calls = 0
    html = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews">Test query</a>
    <a class="result__snippet">Useful <b>current</b> information</a>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        if request.url.host == "api.duckduckgo.com":
            return httpx.Response(200, json={})
        return httpx.Response(200, text=html)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = SearchService(client)
    try:
        first, second = await asyncio.gather(service.search("test query"), service.search("test query"))
        cached = await service.search("test query")
    finally:
        await service.close()

    assert calls == 1  # No preliminary Instant Answer request.
    assert first.results[0].url == "https://example.com/news"
    assert first.results[0].snippet == "Useful current information"
    assert second.results == first.results
    assert cached.cached is True


@pytest.mark.anyio
async def test_search_is_cancelled_when_its_only_conversation_waiter_is_interrupted() -> None:
    cancelled = asyncio.Event()

    class SlowSearch(SearchService):
        async def _perform_search(self, query: str) -> SearchSnapshot:
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    service = SlowSearch()
    task = asyncio.create_task(service.search("slow query"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    await service.close()

@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_extended_request_is_hidden_and_forwarded_without_extra_model_calls(live) -> None:
    import json
    options = []
    class OptionSearch(StubSearch):
        async def search(self, query, **kwargs):
            options.append(kwargs)
            return await super().search(query)
    data = {"query": "GTA VI release date", "fallback_query": "GTA VI Rockstar official", "preferred_domains": ["rockstargames.com"]}
    command = "[[web_search: " + json.dumps(data) + "]]" if live else json.dumps({"web_search": data})
    reply = "[[avatar emotion=neutral gesture=auto intensity=1.0]] Проверила официальное объявление." if live else '{"reply":"Проверила официальное объявление.","emotion":"neutral","intent":"question"}'
    class CharacterChunks(SearchProvider):
        async def stream(self, messages, **kwargs):
            self.seen_messages.append(list(messages))
            content = self.responses[self.calls]
            self.calls += 1
            for char in content:
                yield char
            self.last_response = LLMResponse(content=content, model="test",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12))
    provider = CharacterChunks([command, reply])
    search = OptionSearch(snapshot())
    agent = CharacterAgent(provider, History(), 0,
                           situational_coordinator=Coordinator(search), runtime_settings=RuntimeSettings())
    if live:
        visible = "".join([part async for part in agent.stream_user_message("s", "Расскажи об игре", persist_reply=False)])
    else:
        visible = (await agent.handle_user_message("s", "Расскажи об игре", persist_reply=False))["reply"]
    assert "web_search" not in visible and "rockstargames.com" not in visible
    assert "Проверила официальное объявление" in visible
    assert provider.calls == 2 and len(search.queries) == 1
    assert options == [{"fallback_query": data["fallback_query"], "preferred_domains": ("rockstargames.com",)}]
    assert agent.token_metadata()["total_tokens"] == 24


@pytest.mark.anyio
async def test_prefetched_news_search_never_executes_again() -> None:
    from apps.backend.app.environment.coordinator import SituationalEnrichment
    search = StubSearch(snapshot())
    class Prefetched(Coordinator):
        async def resolve_turn(self, *args, **kwargs):
            return SituationalEnrichment("Свежие внешние факты", "[Контекст окружения: тест]", search=snapshot())
    provider = SearchProvider([
        '{"web_search":{"query":"повтор"}}',
        '{"reply":"Проверила данные.","emotion":"neutral","intent":"question"}',
    ])
    agent = CharacterAgent(provider, History(), 0,
                           situational_coordinator=Prefetched(search), runtime_settings=RuntimeSettings())
    result = await agent.handle_user_message("s", "Новости", persist_reply=False)
    assert result["reply"] == "Проверила данные."
    assert search.queries == []
    assert agent.last_web_search_metadata["status"] == "ok"


@pytest.mark.anyio
async def test_explicit_internet_prohibition_overrides_model_search_command() -> None:
    search = StubSearch(snapshot())
    provider = SearchProvider([
        '{"web_search":{"query":"GTA VI"}}',
        '{"reply":"Без интернет-проверки точную дату не подтвержу.","emotion":"neutral","intent":"question"}',
    ])
    agent = CharacterAgent(provider, History(), 0,
                           situational_coordinator=Coordinator(search), runtime_settings=RuntimeSettings())
    await agent.handle_user_message("s", "Не ищи в интернете. Когда выйдет GTA VI?", persist_reply=False)
    assert search.queries == []
    assert agent.last_web_search_metadata["status"] == "unavailable"

@pytest.mark.anyio
async def test_initial_environment_envelope_is_included_in_context_budget() -> None:
    class LongAmbient(Coordinator):
        async def get_ambient_header(self, **kwargs):
            return "[Контекст окружения: " + "x" * 2000 + "]"
    provider = SearchProvider(['{"reply":"Привет!","emotion":"neutral","intent":"casual_chat"}'])
    agent = CharacterAgent(provider, History(), 0,
                           situational_coordinator=LongAmbient(StubSearch(snapshot())),
                           runtime_settings=RuntimeSettings())
    await agent.handle_user_message("s", "Привет!", persist_reply=False)
    external = [m.content for m in provider.seen_messages[0] if m.content.startswith("Текущая обстановка и время:")]
    assert len(external) == 1 and len(external[0]) <= 1600


@pytest.mark.parametrize("user_text", [
    "Ирис привет", "ну я пошел чинить тогда", "поиск опять плохо работает",
    "Найди ошибку в этом коде", "Найди опечатки в тексте", "Переведи: когда выйдет GTA 6",
    "Не ищи, когда выйдет GTA 6", "Найди почту test@example.com", "Как найти площадь круга?",
    "Ты умеешь найти сведения в интернете?", "Я сам поищу дату выхода GTA 6",
])
def test_search_planner_keeps_casual_local_private_and_forbidden_turns_offline(user_text):
    from apps.backend.app.agents.character.search_intent import plan_search
    assert plan_search(user_text) is None


@pytest.mark.parametrize("user_text", ["найди релиз гта шесть", "Когда выйдет GTA VI?", "when will GTA six release?"])
def test_search_planner_preserves_spoken_product_versions(user_text):
    from apps.backend.app.agents.character.search_intent import plan_search
    planned = plan_search(user_text)
    assert planned.query == "GTA VI дата выхода"
    assert planned.preferred_domains == ("rockstargames.com",)
    pc = plan_search("Когда выйдет GTA 6 на ПК?")
    assert "ПК" in pc.query
    assert "ПК" in pc.fallback_query


def test_search_planner_uses_recent_user_topic_for_corrections_without_transcript():
    from apps.backend.app.agents.character.search_intent import plan_search
    from apps.backend.app.llm.base import ChatMessage
    messages = [ChatMessage(role="user", content="найти про гта шесть когда релиз"),
                ChatMessage(role="assistant", content="Поиск сломан, ща посмотрю."),
                ChatMessage(role="user", content="так с нет ты в смысле найди не я"),
                ChatMessage(role="user", content="ты пиздишь по моему ты не лезешь искать"),
                ChatMessage(role="user", content="але блять ирис ебаный в свет")]
    # The earlier factual question is the topic, never assistant claims or chat history.
    request = plan_search("ну что там с поиском то ебаный свет", messages)
    assert request.query == "GTA VI дата выхода"
    assert plan_search("Ну и что там", [ChatMessage(role="assistant", content="Когда выйдет GTA VI?")]) is None
    assert plan_search("Ну и что там", [*messages, ChatMessage(role="user", content="Привет")]) is None


@pytest.mark.anyio
async def test_live_acknowledgement_precedes_search_and_answer_in_same_turn():
    gate = asyncio.Event()
    started = asyncio.Event()
    class GatedSearch(StubSearch):
        async def search(self, query, **kwargs):
            started.set()
            await gate.wait()
            return await super().search(query, **kwargs)
    search = GatedSearch(snapshot())
    provider = SearchProvider(["Проверила: дата официально объявлена."])
    history = History()
    agent = CharacterAgent(provider, history, 10,
                           situational_coordinator=Coordinator(search), runtime_settings=RuntimeSettings())
    stream = agent.stream_user_message("s", "Когда выйдет гта шесть?")
    first = await anext(stream)
    assert "Так, секунду, проверю." in first
    continuation = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), 1)
    assert not continuation.done() and provider.calls == 0
    gate.set()
    answer = await continuation
    tail = "".join([part async for part in stream])
    assert "Проверила" in answer + tail
    assert provider.calls == 1 and len(search.queries) == 1
    assert "секунду" in history.saved[-1][2]
    assert "Проверила" in history.saved[-1][2]
    external = [m.content for m in provider.seen_messages[0] if m.content.startswith("Окружение и текущее время:")]
    assert len(external[0]) <= 1600
    assert agent.token_metadata()["total_tokens"] == 12


@pytest.mark.anyio
async def test_live_search_decision_with_avatar_prefix_bypasses_speech_style_guards():
    class StreetStyle:
        def resolve(self, _episode):
            return "street"
    command = "[[avatar emotion=neutral gesture=auto intensity=1.0]][[web_search: GTA VI release date]]"
    answer = "[[avatar emotion=neutral gesture=auto intensity=1.0]] Бля, проверила GTA VI: дата объявлена."
    class CharacterChunks(SearchProvider):
        async def stream(self, messages):
            self.seen_messages.append(list(messages))
            content = self.responses[self.calls]
            self.calls += 1
            for char in content:
                yield char
            self.last_response = LLMResponse(content=content, model="test", usage=LLMUsage(prompt_tokens=10,completion_tokens=2,total_tokens=12))
    provider = CharacterChunks([command, answer])
    search = StubSearch(snapshot())
    agent = CharacterAgent(provider, History(), 0, situational_coordinator=Coordinator(search),
                           runtime_settings=RuntimeSettings(), dialogue_style_service=StreetStyle())
    visible = "".join([part async for part in agent.stream_user_message("s", "Расскажи про игру", persist_reply=False)])
    assert "web_search" not in visible and "GTA VI: дата объявлена" in visible
    assert "секунду" in visible
    assert provider.calls == 2 and len(search.queries) == 1
    assert agent.token_metadata()["total_tokens"] == 24


@pytest.mark.anyio
async def test_cancelling_after_acknowledgement_cancels_search_without_fake_answer():
    cancelled = asyncio.Event()
    started = asyncio.Event()
    class SlowSearch(StubSearch):
        async def search(self, query, **kwargs):
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise
    history = History()
    provider = SearchProvider([])
    agent = CharacterAgent(provider, history, 0, situational_coordinator=Coordinator(SlowSearch(snapshot())), runtime_settings=RuntimeSettings())
    stream = agent.stream_user_message("s", "Когда выйдет GTA 6?")
    assert "секунду" in await anext(stream)
    continuation = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), 1)
    continuation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await continuation
    await asyncio.wait_for(cancelled.wait(), 1)
    assert provider.calls == 0
    assert all(role != "assistant" for _, role, _ in history.saved)


@pytest.mark.anyio
async def test_same_year_release_conflict_refines_before_reading_pages():
    old = "https://www.rockstargames.com/old"
    current = "https://www.rockstargames.com/current"
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        body = request.content.decode()
        if "latest" in body:
            html = f'<a class="result__a" href="{current}">GTA VI November 19, 2026</a><div class="result__snippet">GTA VI official release November 19, 2026</div>'
        else:
            html = f'<a class="result__a" href="{old}">GTA VI May 26, 2026</a><div class="result__snippet">GTA VI official release May 26, 2026</div><a class="result__a" href="https://news.example/gta">GTA VI 19 ноября 2026</a><div class="result__snippet">GTA VI release November 19, 2026</div>'
        return httpx.Response(200,text=html)
    class NoPageNetwork(SearchService):
        async def _page(self, result, query):
            return result
    service = NoPageNetwork(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        found = await service.search("GTA VI дата выхода", fallback_query="GTA VI latest official", preferred_domains=("rockstargames.com",))
    finally:
        await service.close()
    assert len(calls) == 2
    assert all("duckduckgo" in call for call in calls)
    assert found.results[0].url == current and found.results[1].url == old
    assert len(found.attempts) == 2


def test_same_release_date_in_two_languages_does_not_trigger_extra_search():
    from apps.backend.app.environment.search_service import _conflicting_date_claims
    items = [SearchResult("GTA VI May 26, 2026", "", "https://example.com/en"),
             SearchResult("GTA VI 26 мая 2026", "", "https://example.com/ru")]
    assert not _conflicting_date_claims(items)


@pytest.mark.anyio
async def test_voice_pipeline_speaks_ack_before_search_finishes_and_completes_answer(monkeypatch):
    from apps.backend.app.voice.live import VoiceSessionManager
    from apps.backend.app.voice.providers import AudioChunk
    gate = asyncio.Event()
    spoken_ack = asyncio.Event()
    class GatedSearch(StubSearch):
        async def search(self, query, **kwargs):
            await gate.wait()
            return await super().search(query, **kwargs)
    class RecordingTTS:
        async def stream(self, request):
            yield AudioChunk(request.text.encode(), "wav", 0, is_final=True)
    class Connection:
        def __init__(self):
            self.events, self.spoken = [], []
        async def json(self, payload):
            self.events.append(payload)
        async def segment(self, started, audio, finished):
            text = audio.decode()
            self.spoken.append(text)
            if "секунду" in text:
                spoken_ack.set()
    provider = SearchProvider(["[[avatar emotion=neutral gesture=auto intensity=1.0]] Проверила: релиз объявлен."])
    agent = CharacterAgent(provider, History(), 10, situational_coordinator=Coordinator(GatedSearch(snapshot())), runtime_settings=RuntimeSettings())
    manager = VoiceSessionManager(RecordingTTS(), idle_flush_ms=10)
    monkeypatch.setattr(manager, "_validate_audio", lambda *_args: 0.1)
    connection = Connection()
    manager._connections["s"] = connection
    task = await manager.start(session_id="s", utterance_id="u", transcript="Когда выйдет гта шесть?", language="ru", voice="ru_f1", agent=agent)
    try:
        await asyncio.wait_for(spoken_ack.wait(), 2)
        assert provider.calls == 0
        assert not task.done()
        gate.set()
        await asyncio.wait_for(task, 2)
    finally:
        gate.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert any("Проверила: релиз объявлен" in text for text in connection.spoken)
    completed = [e for e in connection.events if e["type"] == "voice.text.completed"]
    assert len(completed) == 1
    assert "секунду" in completed[0]["reply"] and "Проверила" in completed[0]["reply"]
    assert "web_search" not in completed[0]["reply"] and "https://" not in completed[0]["reply"]
    assert not any(e["type"] == "voice.error" for e in connection.events)


@pytest.mark.anyio
async def test_slow_optional_ambient_does_not_hold_search_answer():
    ambient_cancelled = asyncio.Event()
    ambient_started = asyncio.Event()
    class SlowAmbient(Coordinator):
        async def get_ambient_header(self, **kwargs):
            ambient_started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                ambient_cancelled.set()
                raise
    class StartedSearch(StubSearch):
        async def search(self, query, **kwargs):
            await ambient_started.wait()
            return await super().search(query, **kwargs)
    search = StartedSearch(snapshot())
    provider = SearchProvider(['{"reply":"Проверила дату релиза.","emotion":"neutral","intent":"question"}'])
    agent = CharacterAgent(provider, History(), 0, situational_coordinator=SlowAmbient(search), runtime_settings=RuntimeSettings())
    result = await asyncio.wait_for(agent.handle_user_message("s", "Когда выйдет GTA VI?", persist_reply=False), timeout=1)
    assert "Проверила" in result["reply"]
    assert len(search.queries) == 1 and provider.calls == 1
    assert ambient_cancelled.is_set()


def test_short_retry_uses_recent_search_topic():
    from apps.backend.app.agents.character.search_intent import plan_search
    from apps.backend.app.llm.base import ChatMessage
    topic = [ChatMessage(role="user",content="Когда выйдет GTA VI?")]
    assert plan_search("Поищи еще раз", topic).query == "GTA VI дата выхода"
    assert plan_search("Поищи еще раз") is None
