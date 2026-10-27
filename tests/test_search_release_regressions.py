"""Failures from the October 24 dialogue: routing, stale schedules and retries."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import json
import time
from xml.sax.saxutils import escape

import httpx
import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.search_intent import SearchRequest, plan_search
from apps.backend.app.coding.orchestration import CodingBridge
from apps.backend.app.environment.search_service import SearchResult, SearchService, _ArticleParser
from apps.backend.app.environment.release_evidence import release_evidence_problem
from tests.test_search_recovery import Environment, History, Lookup, ReplayLLM


@pytest.fixture
def anyio_backend():
    return "asyncio"


def bridge(enabled=False):
    return CodingBridge(SimpleNamespace(enabled=enabled, store=None,
        runtime_settings=SimpleNamespace(coding_auto_delegate=True)))


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("text", [
    "можешь пожалуйста рассказать какой последний агент вышел в игре дедлок",
    "давай еще раз пожалуйста поищи",
    "какой нахуй кодинг агент блять",
    "дай информацию про последнего агента Deadlock",
    "исправь ошибку в дате выхода персонажа",
    "Проверь новости про протесты",
])
def test_game_and_search_are_never_coding_tasks(enabled, text):
    routing = bridge(enabled)
    assert routing.observe_user_message("s", text) is None
    assert not routing.should_request_model_delegation(text)
    assert not routing._deferred_objectives


@pytest.mark.parametrize("enabled", [False, True])
def test_search_cannot_confirm_a_deferred_coding_task(enabled):
    routing = bridge(False)
    assert routing.observe_user_message("s", "Передай агенту задачу: напиши Python файл")
    routing.service.enabled = enabled
    assert routing.observe_user_message("s", "давай еще раз пожалуйста поищи") is None
    assert routing.observe_user_message("s", "давай") is None


@pytest.mark.anyio
async def test_dated_old_guide_does_not_stop_crosschecking_latest_release():
    now = datetime.now(UTC)
    stale = SearchResult("Deadlock: все герои", "Violet выйдет 20 октября", "https://guide.example/heroes",
                         published_at=(now - timedelta(days=11)).isoformat())
    fresh = SearchResult("Deadlock: Nurse Harrow is out now", "Nurse Harrow is now available in Deadlock.",
                         "https://store.steampowered.com/news/app/1422450/view/123",
                         published_at=(now - timedelta(days=4)).isoformat())
    calls = []
    service = SearchService()
    async def provider(name, query):
        calls.append(name)
        if name == "official_feed":
            return [], "empty"
        return ([stale] if name == "duckduckgo" else [fresh]), "ok"
    async def page(result, query):
        return replace(result, page_status="read", page_text=result.snippet)
    service._provider, service._page = provider, page
    snapshot = await service.search("Deadlock последний вышедший герой 2026")
    assert len(calls) >= 2
    assert snapshot.results[0].url == fresh.url


@pytest.mark.anyio
async def test_native_search_retry_bypasses_cache_even_if_model_omits_flag():
    lookup = Lookup()
    agent = CharacterAgent(ReplayLLM([]), History(), 8, situational_coordinator=Environment(lookup))
    agent._search_user_text = "попробуй ещё раз пожалуйста поищи"
    await agent._perform_web_search(SearchRequest("Deadlock новый герой"))
    assert lookup.calls[0][1]["force_refresh"] is True


def test_article_release_table_keeps_names_and_dates_in_same_rows():
    parser = _ArticleParser()
    parser.feed('<article><h1>Deadlock release dates</h1><table>'
        '<tr><th>Hero</th><th>Release date</th></tr>'
        '<tr><td>Violet</td><td>October 16, 2026</td></tr>'
        '<tr><td>Nurse Harrow</td><td>October 20, 2026</td></tr></table></article>')
    evidence, _ = parser.evidence("Deadlock release dates")
    assert "Violet" in evidence and "Nurse Harrow" in evidence
    assert "Violet October 16, 2026" in " ".join(evidence.split())


def test_spoken_game_agent_is_planned_as_a_hero_lookup():
    planned = plan_search("можешь рассказать какой последний агент вышел в игре дедлок")
    assert planned.query == "deadlock последний новый герой"


@pytest.mark.parametrize("quote", [
    "Nurse Harrow will join us next Tuesday.",
    "Nurse Harrow is not yet released.",
    "Violet is available in-game now!",
    "Nurse Harrow is available now. This quote was invented.",
])
def test_release_quote_must_prove_the_named_entity_and_actual_event(quote):
    result = SearchResult("Deadlock", "", "https://store.steampowered.com/news/app/1422450/view/123",
        page_status="read", page_text="Nurse Harrow is available now. Violet is available in-game now!",
        published_at=datetime.now(UTC).isoformat())
    assert release_evidence_problem([result], "Deadlock latest hero", quote, "Nurse Harrow")


def test_verified_primary_release_is_accepted_and_excerpt_keeps_the_announcement():
    quote = "With Nurse Harrow joining us today, that marks the end of our hero releases."
    result = SearchResult("Deadlock", "", "https://store.steampowered.com/news/app/1422450/view/123",
        page_status="read", page_text=quote + "\n" + "Hero voters: statistics.\n" * 70,
        published_at=datetime.now(UTC).isoformat())
    assert not release_evidence_problem([result], "Deadlock latest hero", quote, "Nurse Harrow", ("store.steampowered.com",))
    snapshot = SearchService._snapshot("Deadlock latest hero", status="ok", results=[result])
    assert quote in snapshot.compact_summary()


@pytest.mark.parametrize("queries", [
    ["Deadlock latest hero", "Minecraft release date"],
    ["Deadlock latest hero", "Deadlock password: private-token"],
    ["Deadlock latest hero", "Deadlock release date", "Deadlock update", "Deadlock patch"],
])
def test_search_batch_never_drops_an_unrelated_private_or_excess_call(queries):
    calls = [{"function": {"name": "web_search", "arguments": json.dumps({"query": q})}} for q in queries]
    assert CharacterAgent._coalesce_search_calls(calls) is None


def test_protocol_diagnostics_never_include_authorization_header_bytes():
    from apps.backend.app.llm.providers.deepseek import _root_exception_detail
    error = ValueError("Illegal header value b'Bearer fake-test-credential'")
    assert _root_exception_detail(error) == "ValueError"


def test_a_user_forum_post_on_the_official_domain_is_not_a_release_source():
    quote = "Nurse Harrow is available now in Deadlock."
    result = SearchResult("My new hero idea", "", "https://forums.playdeadlock.com/threads/hero-idea.1/",
        page_status="read", page_text=quote, published_at=datetime.now(UTC).isoformat())
    assert release_evidence_problem([result], "Deadlock latest hero", quote, "Nurse Harrow", ("playdeadlock.com",))


@pytest.mark.anyio
async def test_new_hero_query_reads_official_feed_without_a_search_engine():
    date = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    text = "Nurse Harrow now joins us today. This marks the end of our hero releases."
    calls = []
    def handler(request):
        calls.append(str(request.url))
        assert request.url.host == "store.steampowered.com"
        return httpx.Response(200, text='<rss><channel><item><title>New arrival</title>'
            '<link>https://store.steampowered.com/news/app/1422450/view/123</link>'
            f'<pubDate>{date}</pubDate><description>{escape("<p>" + text + "</p>")}</description>'
            '</item></channel></rss>')
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        result = await service.search("Deadlock новый герой агент 2026")
        assert len(calls) == 1
        assert result.results[0].provider == "official_feed"
        assert result.results[0].page_status == "read"
        assert text in result.results[0].page_text
    finally:
        await service.close()


@pytest.mark.anyio
async def test_guessed_secondary_domain_does_not_demote_a_known_official_source():
    quote = "Nurse Harrow is available now in Deadlock."
    class PrimarySearch(SearchService):
        async def search(self, query, **options):
            assert "store.steampowered.com" in options["preferred_domains"]
            options["budget"].admit(query)
            return self._snapshot(query, status="ok", results=[SearchResult(
                "Deadlock release", "", "https://store.steampowered.com/news/app/1422450/view/123",
                published_at=datetime.now(UTC).isoformat(), page_status="read", page_text=quote)])
    llm = ReplayLLM([json.dumps({"enough": True, "source_ids": ["S1"],
        "canonical_entity": "Nurse Harrow", "supporting_quote": quote})])
    agent = CharacterAgent(llm, History(), 8)
    result = await agent._run_search_cycle(PrimarySearch(),
        SearchRequest("Deadlock последний новый герой", preferred_domains=("deadlock.wiki",)), {})
    assert result.evidence_status == "sufficient" and result.supporting_quote == quote
    assert len(llm.calls) == 1


@pytest.mark.anyio
async def test_assessor_cannot_confirm_latest_release_from_future_schedule():
    class ScheduleSearch(SearchService):
        async def search(self, query, **options):
            options["budget"].admit(query)
            return self._snapshot(query, status="ok", results=[SearchResult(
                "Deadlock release schedule", "Violet выйдет 20 октября 2026 года.",
                "https://guide.example/heroes", published_at="2026-10-13T00:00:00+00:00",
                page_status="read", page_text="Violet выйдет 20 октября 2026 года.")])
    llm = ReplayLLM([json.dumps({"enough": True, "source_ids": ["S1"],
        "canonical_entity": "Violet", "supporting_quote": "Violet выйдет 20 октября 2026 года."})] * 3)
    agent = CharacterAgent(llm, History(), 8)
    agent._retrieval_deadline = time.monotonic() + 15
    result = await agent._run_search_cycle(ScheduleSearch(), SearchRequest("Deadlock последний вышедший герой"), {})
    assert result.evidence_status != "sufficient"
    assert result.metadata()["evidence_warnings"]
