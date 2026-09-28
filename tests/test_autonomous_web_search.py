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

    async def search(self, query: str) -> SearchSnapshot:
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

    result = await agent.handle_user_message("s", "Какая сейчас версия Python?", persist_reply=False)

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
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews">Example title</a>
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

    assert calls == 2
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
