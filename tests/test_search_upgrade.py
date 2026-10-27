"""Search quality, latency and conversational waiting regressions."""
import asyncio
import json
import time
from dataclasses import replace

import pytest
from pydantic import ValidationError

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.search_intent import refinement_preserves_subject
from apps.backend.app.environment.search_service import SearchService, SearchResult, SearchTurnBudget
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.skills.runtime import SearchArguments, SkillCall, parse_skill
from tests.test_search_recovery import Environment, History, Lookup, ReplayLLM


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_blank_query_never_becomes_a_network_request(query):
    with pytest.raises(ValidationError):
        SearchArguments(query=query)


def test_empty_optional_fallback_does_not_invalidate_a_good_query():
    assert SearchArguments(query="Python documentation", fallback_query="  ").fallback_query is None


def test_full_search_command_fits_stream_parser_and_preserves_exact_error():
    arguments = SearchArguments(query='Python 3.12 "ModuleNotFoundError" Windows',
        fallback_query="Python 3.12 import error Windows " + "package " * 30,
        preferred_domains=[(letter * 60 + ".") * 4 + "org" for letter in "abc"], acknowledgement="Хм, сверю одну деталь.")
    command = "[[skill: " + SkillCall(name="web_search", arguments=arguments.model_dump()).model_dump_json() + "]]"
    recognized, call = parse_skill(command, live=True)
    assert recognized and call is not None
    assert '"ModuleNotFoundError"' in call.arguments["query"]


@pytest.mark.parametrize(("original", "refined", "allowed"), [
    ("Python ошибка установки пакета Windows", "Python Windows pip install troubleshooting", True),
    ("Python 3.12 ошибка установки", "Python 3.13 installation error", False),
    ("Python 3.12 ошибка установки", "Python 12.3 installation error", False),
    ('Python "ModuleNotFoundError" Windows', 'Python "ImportError" Windows', False),
    ("Яндекс дата-центр причина сбоя", "Яндекс дата-центр почему произошла авария", True),
    ("Песня Альфа текст", "Песня Бета текст", False),
    ("Deadlock новый герой", "Overwatch new hero", False),
    ("Python site:docs.python.org ошибка установки", "Python install troubleshooting", True),
])
def test_refinement_can_rephrase_without_losing_name_version_or_quote(original, refined, allowed):
    assert refinement_preserves_subject(original, refined) is allowed


@pytest.mark.anyio
async def test_acknowledgement_stays_local_and_needs_no_extra_generation(monkeypatch):
    monkeypatch.setattr("apps.backend.app.agents.character.agent._SEARCH_ACK_DELAY_SECONDS", .001)
    llm = ReplayLLM([])
    llm.supports_native_tools = True
    class SlowLookup(Lookup):
        async def search(self, query, **options):
            await asyncio.sleep(.03)
            return await super().search(query, **options)
    lookup = SlowLookup()
    agent = CharacterAgent(llm, History(), 8, situational_coordinator=Environment(lookup))
    call = SkillCall(name="web_search", arguments={"query": "Deadlock новый герой", "acknowledgement": "М-м, где же он…"})
    parts = [part async for part in agent._wait_for_lookup(agent._perform_skill(call), acknowledge=True)]
    assert parts[0][0].startswith("М-м, где же он…")
    assert parts[-1][1].status == "ok" and not llm.calls
    assert lookup.calls == [("Deadlock новый герой", {"fallback_query": None, "preferred_domains": ()})]


@pytest.mark.anyio
async def test_native_voice_waiting_reaction_survives_streaming_and_is_not_spoken_twice(monkeypatch):
    from apps.backend.app.llm.providers import deepseek as module
    from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
    from tests.test_deepseek_provider import FakeClient, FakeStream, _settings, _chunk
    from tests.test_native_conversation_tools import tool_chunk
    monkeypatch.setattr("apps.backend.app.agents.character.agent._SEARCH_ACK_DELAY_SECONDS", .001)
    reaction = "М-м, где же он…"
    arguments = json.dumps({"query": "Deadlock новый герой", "acknowledgement": reaction,
        "fallback_query": "Deadlock new hero " + "release " * 30,
        "preferred_domains": [(letter * 60 + ".") * 4 + "org" for letter in "abc"]}, ensure_ascii=False)
    assert len(arguments) > 1024
    decision = [tool_chunk("web_search", id="search-waiting")]
    decision += [tool_chunk(arguments=letter) for letter in arguments]
    decision += [_chunk(finish_reason="tool_calls")]
    fake = FakeClient([FakeStream(decision), FakeStream([_chunk(reaction + " Проверка завершена."), _chunk(finish_reason="stop")])])
    monkeypatch.setattr(module, "_shared_client", lambda *_: fake)
    class SlowLookup(Lookup):
        async def search(self, query, **options):
            await asyncio.sleep(.03)
            return await super().search(query, **options)
    lookup = SlowLookup()
    agent = CharacterAgent(DeepSeekProvider(_settings()), History(), 8, situational_coordinator=Environment(lookup))
    visible = "".join([delta async for delta in agent.stream_user_message("s", "Поищи нового героя Deadlock", persist_reply=False)])
    assert visible.count(reaction) == 1 and "Проверка завершена." in visible
    assert "[[skill" not in visible and "fallback_query" not in visible
    assert len(fake.completions.calls) == 2 and len(lookup.calls) == 1
    assert "acknowledgement" not in lookup.calls[0][1]


def test_waiting_reaction_is_not_recycled_from_recent_reply():
    agent = CharacterAgent(ReplayLLM([]), History(), 8)
    agent._bridge_context = [ChatMessage(role="assistant", content="Хм, сверю одну деталь. Вчера вышло обновление.")]
    assert not agent._fresh_search_bridge("Хм, сверю одну деталь…")
    assert agent._fresh_search_bridge("Так, а вот это интересно…")
    assert not agent._valid_bridge("<voice>Результат</voice>")


@pytest.mark.anyio
async def test_fast_engine_does_not_start_a_second_request():
    service = SearchService()
    calls = []
    async def provider(name, query):
        calls.append(name)
        return [SearchResult("Python", "Python programming", "https://python.org/doc/")], "ok"
    service._provider = provider
    try:
        snapshot = await service.search("Python documentation")
        assert snapshot.status == "ok" and calls == ["duckduckgo"]
    finally:
        await service.close()


@pytest.mark.anyio
async def test_slow_engine_is_cancelled_when_free_fallback_finds_relevant_evidence():
    service = SearchService()
    service._hedge_delay_seconds = .01
    cancelled = asyncio.Event()
    async def provider(name, query):
        if name == "duckduckgo":
            try:
                await asyncio.sleep(2)
            finally:
                cancelled.set()
        return [SearchResult("Python", "Python programming", "https://python.org/doc/", provider=name)], "ok"
    service._provider = provider
    budget = SearchTurnBudget(time.monotonic() + 1)
    started = time.monotonic()
    try:
        snapshot = await service.search("Python documentation", budget=budget)
        assert time.monotonic() - started < .3
        assert cancelled.is_set() and snapshot.status == "ok"
        assert snapshot.provider == "bing" and budget.requests == 2
        assert {a["status"] for a in snapshot.attempts} == {"ok", "cancelled"}
    finally:
        await service.close()


@pytest.mark.anyio
async def test_fast_unrelated_fallback_does_not_cancel_relevant_primary():
    service = SearchService()
    service._hedge_delay_seconds = .001
    async def provider(name, query):
        if name == "duckduckgo":
            await asyncio.sleep(.025)
            return [SearchResult("Python", "Python programming", "https://python.org/doc/")], "ok"
        return [SearchResult("Roblox", "Pet simulator", "https://example.org/game")], "ok"
    service._provider = provider
    try:
        snapshot = await service.search("Python documentation")
        assert snapshot.results[0].url == "https://python.org/doc/"
    finally:
        await service.close()


def test_richer_document_wins_over_earlier_snippet_for_same_canonical_url():
    service = SearchService()
    snippet = SearchResult("Python", "Python", "https://python.org/doc/?utm_source=x")
    document = replace(snippet, url="https://python.org/doc/", page_text="Python programming reference", page_status="read")
    assert service._rank("Python", [snippet, document], ()) == [document]


@pytest.mark.anyio
async def test_primary_domain_is_searched_first_and_dates_reach_free_engine():
    service = SearchService()
    calls = []
    async def provider(name, query):
        calls.append((name, query))
        return [SearchResult("Python", "Python", "https://docs.python.org/3/", published_at="2026-10-24T22:00:00Z")], "ok"
    service._provider = provider
    try:
        snapshot = await service.search("Python documentation", preferred_domains=("docs.python.org",),
            since="2026-10-25T00:00:00+03:00", until="2026-10-26T00:00:00+03:00")
        assert "site:docs.python.org" in calls[0][1]
        assert "after:" in calls[0][1] and "before:" in calls[0][1]
        assert snapshot.results and snapshot.since == "2026-10-25T00:00:00+03:00"
    finally:
        await service.close()


@pytest.mark.anyio
async def test_reading_pages_uses_network_budget_and_keeps_snippet_at_deadline():
    service = SearchService()
    cancelled = asyncio.Event()
    async def provider(name, query):
        return [SearchResult("Python version", "Python version", "https://python.org/downloads/")], "ok"
    async def page(*args):
        try:
            await asyncio.Future()
        finally:
            cancelled.set()
    service._provider, service._page = provider, page
    budget = SearchTurnBudget(time.monotonic() + .03)
    try:
        snapshot = await service.search("Python current version", budget=budget)
        assert snapshot.status == "ok" and snapshot.results
        assert budget.requests == 2 and budget.pages == 1 and cancelled.is_set()
    finally:
        await service.close()


@pytest.mark.anyio
async def test_reading_never_exceeds_last_remaining_network_request():
    service = SearchService()
    async def provider(name, query):
        return [SearchResult("Python version", "Python version", "https://python.org/downloads/"),
                SearchResult("Python version", "Python version", "https://example.org/python")], "ok"
    async def page(result, query):
        return replace(result, page_status="read", page_text="Python version")
    service._provider, service._page = provider, page
    budget = SearchTurnBudget(time.monotonic() + 1, requests=4)
    try:
        await service.search("Python version", budget=budget)
        assert budget.requests == 6 and budget.pages == 1
    finally:
        await service.close()


@pytest.mark.anyio
async def test_separate_turn_budgets_do_not_share_progress_or_deadlines():
    service = SearchService()
    entered = asyncio.Event()
    calls, progress = [], [[], []]
    async def provider(name, query):
        calls.append(name)
        if len(calls) == 2:
            entered.set()
        await entered.wait()
        return [SearchResult("Python", "Python", "https://python.org/")], "ok"
    service._provider = provider
    budgets = [SearchTurnBudget(time.monotonic() + 1) for _ in range(2)]
    try:
        snapshots = await asyncio.gather(*(service.search("Python", budget=budgets[index],
            progress=progress[index].append) for index in range(2)))
        assert all(result.status == "ok" for result in snapshots)
        assert calls == ["duckduckgo", "duckduckgo"]
        assert all(budget.requests == 1 for budget in budgets) and all(progress)
    finally:
        await service.close()


@pytest.mark.anyio
async def test_news_cache_expires_earlier_than_reference_cache(monkeypatch):
    service = SearchService()
    now = time.monotonic()
    async def provider(name, query):
        return [SearchResult("Python news", "Python news", "https://python.org/news/", published_at="2026-10-25T00:00:00Z")], "ok"
    async def page(result, query):
        return replace(result, page_status="read", page_text="Python news")
    service._provider, service._page = provider, page
    try:
        await service.search("Python news", mode="news")
        monkeypatch.setattr("apps.backend.app.environment.search_service.time.monotonic", lambda: now + 61)
        assert not (await service.search("Python news", mode="news")).cached
    finally:
        await service.close()
