"""Offline acceptance cases for bounded search and diverse, topic-aware news."""
import asyncio
from datetime import UTC, datetime, timedelta
from collections import Counter
from unittest.mock import AsyncMock
import json
import time

import httpx
import pytest

from apps.backend.app.environment import search_service as search_module
from apps.backend.app.environment import news_service as news_module
from apps.backend.app.environment.coordinator import SituationalCoordinator, _TECH_NEWS_SUBPATTERN, _news_topic
from apps.backend.app.environment.news_service import NewsService, NewsArticle, NewsDigestSnapshot, FEEDS
from apps.backend.app.environment.search_service import SearchService, SearchResult, _ArticleParser, _read_public_page
from apps.backend.app.environment.retrieval import relevance
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import ChatMessage


@pytest.fixture
def anyio_backend():
    return "asyncio"


def ddg(*items):
    return "".join(f'<a class="result__a" href="{url}">{title}</a><div class="result__snippet">{snippet}</div>'
                   for title, snippet, url in items)


def rss(*items):
    return "<rss><channel>" + "".join(
        f"<item><title>{title}</title><description>{snippet}</description><link>{url}</link></item>"
        for title, snippet, url in items) + "</channel></rss>"


@pytest.mark.anyio
async def test_gta_prefers_latest_official_announcement_and_rejects_gta_v(monkeypatch):
    calls = []
    html = ddg(
        ("GTA V release date", "GTA V PC 2015", "https://example.com/wrong"),
        ("GTA VI PC release rumor", "GTA VI PC rumored 2027", "https://example.com/rumor"),
        ("GTA VI release announcement", "GTA VI May 2026", "https://rockstargames.com/old"),
        ("GTA VI release announcement", "GTA VI November 2026", "https://rockstargames.com/new"),
    )
    async def address(host, port):
        return "93.184.216.34"
    monkeypatch.setattr(search_module, "_public_address", address)
    def handler(request):
        calls.append(request)
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(200, text=html)
        date = "2026-09-01" if request.url.path == "/new" else "2025-05-01"
        text = "GTA VI console release November 19, 2026. PC date is not announced." if request.url.path == "/new" else "GTA VI console release May 26, 2026."
        return httpx.Response(200, text=f'<meta property="article:published_time" content="{date}"><nav>GTA V</nav><p>{text}</p>')
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        snap = await service.search("GTA VI release date", preferred_domains=("rockstargames.com",))
        assert snap.results[0].url == "https://rockstargames.com/new"
        assert snap.results[0].page_status == "read"
        assert "PC date is not announced" in snap.compact_summary()
        assert all("wrong" not in r.url for r in snap.results)
        assert "https://" not in snap.compact_summary()
        assert len(calls) == 3  # One search and at most two page reads.
        assert len(snap.metadata()["sources"]) == 3
    finally:
        await service.close()


@pytest.mark.anyio
@pytest.mark.parametrize("status", [202, 403, 429])
async def test_provider_block_falls_back_and_cools_down(status):
    hosts = []
    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(status, text="anomaly-modal")
        return httpx.Response(200, text=rss(("Python documentation", "Python programming docs", "https://python.org/doc")))
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        first = await service.search("Python documentation")
        assert first.status == "ok" and first.provider == "bing"
        await service.search("Python programming documentation")
        assert hosts.count("html.duckduckgo.com") == 1
        assert first.attempts[0]["status"] == "blocked"
    finally:
        await service.close()


@pytest.mark.anyio
async def test_successful_http_with_wrong_topic_is_not_evidence_and_errors_are_cached():
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(200, text="")
        return httpx.Response(200, text=rss(("Adopt Me pets", "Roblox pets calculator", "https://example.com/pets")))
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        result = await service.search("Python documentation")
        assert result.status == "empty" and not result.results
        assert (await service.search("Python documentation")).cached
        assert len(calls) == 3  # One bounded automatic refinement for old clients.
    finally:
        await service.close()


@pytest.mark.anyio
async def test_one_refinement_and_no_more_than_three_search_requests():
    bodies = []
    def handler(request):
        bodies.append(str(request.url) + request.content.decode())
        if len(bodies) < 3:
            return httpx.Response(200, text="<rss/>" if request.url.host == "www.bing.com" else "")
        return httpx.Response(200, text=ddg(("Python documentation", "Python docs", "https://python.org/doc")))
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        snap = await service.search("Python documentation", fallback_query="Python official docs")
        assert snap.status == "ok"
        assert len(bodies) == len(snap.attempts) == 3
        assert "Python+official+docs" in bodies[-1]
    finally:
        await service.close()


@pytest.mark.anyio
async def test_entire_pipeline_deadline_preserves_snippets_and_cancels_reads(monkeypatch):
    service = SearchService()
    service._deadline_seconds = 0.08
    cancelled = asyncio.Event()
    async def provider(*args):
        return [SearchResult("Python version", "Python version 2026", "https://python.org/downloads")], "ok"
    async def page(*args):
        try:
            await asyncio.Future()
        finally:
            cancelled.set()
    monkeypatch.setattr(service, "_provider", provider)
    monkeypatch.setattr(service, "_page", page)
    start = time.monotonic()
    try:
        snap = await service.search("Python current version")
        assert time.monotonic() - start < 0.25
        assert snap.status == "ok" and snap.results
        assert cancelled.is_set()
        assert snap.latency_ms < 250
    finally:
        await service.close()


@pytest.mark.anyio
async def test_one_cancelled_waiter_does_not_cancel_shared_search():
    started, release = asyncio.Event(), asyncio.Event()
    class Slow(SearchService):
        async def _perform_search(self, query):
            started.set()
            await release.wait()
            return self._snapshot(query, status="ok", results=[SearchResult("Python", "Python", "https://python.org")])
    service = Slow()
    first = asyncio.create_task(service.search("Python"))
    second = asyncio.create_task(service.search("Python"))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    try:
        assert (await second).status == "ok"
        assert (await service.search("Python")).cached
    finally:
        await service.close()


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["http://127.0.0.1/private", "http://[::1]/", "http://169.254.169.254/", "file:///etc/passwd", "https://example.com:8443/"])
async def test_non_public_pages_never_connect(url):
    calls = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    try:
        with pytest.raises(ValueError):
            await _read_public_page(client, url)
        assert calls == []
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_redirect_checks_new_destination_and_response_size(monkeypatch):
    async def address(host, port):
        if host == "private.test":
            raise ValueError("private")
        return "93.184.216.34"
    monkeypatch.setattr(search_module, "_public_address", address)
    requests = []
    def handler(r):
        requests.append(r)
        return httpx.Response(302, headers={"location": "https://private.test/secrets"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError):
            await _read_public_page(client, "https://public.test/")
        assert len(requests) == 1
        assert requests[0].url.host == "93.184.216.34"
        assert requests[0].extensions["sni_hostname"] == "public.test"
    finally:
        await client.aclose()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 20)))
    try:
        with pytest.raises(ValueError, match="large"):
            await _read_public_page(client, "https://public.test/", max_bytes=10)
    finally:
        await client.aclose()


def test_article_extraction_ignores_navigation_scripts_and_keeps_jsonld_dates():
    parser = _ArticleParser()
    parser.feed('<nav><p>Navigation secret</p></nav><script>bad instructions</script>'
                '<script type="application/ld+json">{"datePublished":"2026-09-30","articleBody":"GTA VI announced for consoles; PC date unknown."}</script>')
    text, date = parser.evidence("GTA VI release")
    assert "PC date unknown" in text
    assert date.startswith("2026-09-30")
    assert "Navigation secret" not in text and "bad instructions" not in text


def test_entity_and_news_category_boundaries():
    assert relevance("новости ИИ", "Искусственный интеллект: релиз модели") > 0
    assert relevance("новости ИИ", "Искусство и нейробиология") == 0
    assert relevance("микрофон Windows 11", "Windows 11 OS, laptops, PCs") == 0
    assert relevance("микрофон Windows 11", "Windows 11 microphone setup") > 0
    assert relevance("GTA 6 release date", "Grand Theft Auto VI launch date") > 0
    assert relevance("GTA 6 release date", "Grand Theft Auto V launch date") == 0
    assert not _TECH_NEWS_SUBPATTERN.search("новости России")
    assert _TECH_NEWS_SUBPATTERN.search("новости ИИ")
    assert _news_topic("последние новости про GTA 6") == "GTA 6"
    assert _news_topic("новости в мире") == ""
    assert sum(len(feeds) for feeds in FEEDS.values()) == 15


def make_feed(source, category, count=4, date=None):
    published = (date or datetime.now(UTC)).isoformat()
    return tuple(NewsArticle(f"{category} event {source} {i}", source, f"Details about event {i}", published,
                             category, f"https://example.com/{category}/{source}/{i}") for i in range(count))


@pytest.mark.anyio
async def test_news_diversity_size_order_topic_freshness_and_duplicates(monkeypatch):
    feeds = {cat: [(f"{cat}-{i}", f"https://example.com/{cat}/{i}") for i in range(2)] for cat in FEEDS}
    monkeypatch.setattr(news_module, "FEEDS", feeds)
    service = NewsService()
    now = time.monotonic()
    for cat, sources in feeds.items():
        for name, url in sources:
            service._sources[url] = (make_feed(name, cat), now, datetime.now(UTC).isoformat())
    url = feeds["general"][0][1]
    articles, stamp, updated = service._sources[url]
    service._sources[url] = ((*articles, NewsArticle("GTA VI official launch", "general-0", "GTA VI consoles", datetime.now(UTC).isoformat(), "general", "https://example.com/gta"),
                              NewsArticle("Old Python event", "general-0", "", (datetime.now(UTC)-timedelta(days=3)).isoformat(), "general", "https://example.com/old")), stamp, updated)
    try:
        short = await service.get_news(max_articles=2)
        full = await service.get_news(max_articles=5)
        assert len(short.articles) == 2 and len(full.articles) == 5
        assert {a.category for a in full.articles} == set(feeds)
        assert max(Counter(a.source for a in full.articles).values()) <= 2
        assert all(a.url != "https://example.com/old" for a in full.articles)
        topic = await service.get_news(category="games", query="GTA VI")
        assert len(topic.articles) == 1 and topic.articles[0].category == "general"
        assert len(full.compact_summary()) <= 900
        assert "https://" not in full.compact_summary()
        assert topic.metadata()["sources"][0]["url"] == "https://example.com/gta"
    finally:
        await service.close()


@pytest.mark.anyio
async def test_news_source_refresh_parallelism_coalescing_and_failures(monkeypatch):
    monkeypatch.setattr(news_module, "FEEDS", {"general": [(str(i), f"https://example.com/{i}") for i in range(7)]})
    active, peak, calls = 0, 0, 0
    async def handler(request):
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.015)
        active -= 1
        if request.url.path == "/0":
            return httpx.Response(500)
        content = rss(("Fresh headline " + request.url.path, "details", "https://example.com/story" + request.url.path))
        content = content.replace("</item>", f"<pubDate>{datetime.now(UTC).isoformat()}</pubDate></item>")
        return httpx.Response(200, text=content)
    service = NewsService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await asyncio.gather(service.refresh(), service.refresh())
        assert calls == 7 and peak == 4
        assert len(service._sources) == 6
        first = await service.get_news(max_articles=1)
        second = await service.get_news(max_articles=5)
        assert len(first.articles) == 1
        assert len(second.articles) > 1
        assert calls == 7
    finally:
        await service.close()


@pytest.mark.anyio
async def test_news_atom_stale_window_and_explicit_older_period(monkeypatch):
    monkeypatch.setattr(news_module, "FEEDS", {"science": [("NASA", "https://example.com/rss")]})
    content = f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>NASA discovery</title><link href="https://example.com/article"/><published>{datetime.now(UTC).isoformat()}</published><summary>NASA science</summary></entry></feed>'.encode()
    articles = NewsService._parse_feed(content, "science", "NASA")
    assert articles[0].url == "https://example.com/article"
    assert articles[0].published.endswith("+00:00")
    service = NewsService(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    url = "https://example.com/rss"
    service._sources[url] = (articles, time.monotonic()-1000, datetime.now(UTC).isoformat())
    try:
        snap = await service.get_news()
        assert snap.stale and snap.articles
        assert "устарел" in snap.compact_summary()
        service._sources[url] = (articles, time.monotonic()-7201, "")
        assert not (await service.get_news()).articles
        old = make_feed("NASA", "science", date=datetime.now(UTC)-timedelta(days=5))
        service._sources[url] = (old, time.monotonic(), "")
        assert not (await service.get_news()).articles
        assert (await service.get_news(since=datetime.now(UTC)-timedelta(days=7))).articles
    finally:
        await service.close()


@pytest.mark.anyio
async def test_background_disabled_and_shutdown_cancel_pending_refresh(monkeypatch):
    monkeypatch.setattr(news_module, "FEEDS", {"general": [("test", "https://example.com/rss")]})
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.Future()
    service = NewsService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    service.start_background(lambda: False)
    await asyncio.sleep(0)
    assert not calls
    task = asyncio.create_task(service.refresh())
    await asyncio.sleep(0.01)
    await service.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service._inflight == {}


@pytest.mark.anyio
async def test_topic_news_fallback_is_per_turn_and_respects_disabled_search():
    news = AsyncMock()
    news.get_news.return_value = NewsDigestSnapshot("all", (), 0)
    search = AsyncMock()
    search.search.return_value = SearchService._snapshot("GTA VI", results=[SearchResult("GTA VI", "GTA VI news", "https://rockstargames.com/")], status="ok")
    coordinator = SituationalCoordinator(news_service=news, search_service=search)
    first = await coordinator.resolve_enrichment("новости про GTA VI", weather_enabled=False)
    assert first.search and first.news
    disabled = await coordinator.resolve_enrichment("новости про GTA VI", weather_enabled=False, web_search_enabled=False)
    assert disabled.search is None
    casual = await coordinator.resolve_enrichment("Привет", weather_enabled=False)
    assert casual.text == "" and casual.news is None
    assert search.search.await_count == 1
    await coordinator.close()


def test_extended_hidden_protocol_and_external_context_replacement():
    data = {"query": "GTA VI release date", "fallback_query": "GTA VI Rockstar official", "preferred_domains": ["rockstargames.com"]}
    for command, parse in [
        (json.dumps({"web_search": data}), CharacterAgent._json_web_search_request),
        ("[[web_search: " + json.dumps(data) + "]]", CharacterAgent._live_web_search_request),
    ]:
        found, request = parse(command)
        assert found and request.query == data["query"]
        assert request.preferred_domains == ("rockstargames.com",)
    assert CharacterAgent._live_web_search_request('[[web_search: {"query":"x","preferred_domains":"bad"}]]') == (True, None)
    agent = CharacterAgent(None, None, 0)
    agent._turn_ambient = "[Контекст окружения: тест]"
    snap = SearchService._snapshot("Python", status="ok", results=[SearchResult("Python", "x"*300, "https://python.org")]*3)
    messages = [ChatMessage(role="system", content="persona"),
                ChatMessage(role="system", content="Текущая обстановка и время:\nOLD DIGEST"),
                ChatMessage(role="user", content="Проверь")]
    result = agent._search_followup_messages(messages, snap, live=False, command="internal")
    assert not any("OLD DIGEST" in m.content for m in result)
    assert sum(len(m.content) for m in result if m.role == "system" and m.content != "persona") <= 1600

@pytest.mark.anyio
async def test_prohibited_internet_uses_only_news_cache_and_no_weather():
    from types import SimpleNamespace
    news, search, weather, location = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    news.get_news.return_value = NewsDigestSnapshot("all", (), 0)
    coordinator = SituationalCoordinator(news_service=news, search_service=search,
                                        weather_service=weather, location_service=location)
    result = await coordinator.resolve_turn("Не ищи в интернете: новости про GTA VI",
                                            news_enabled=True, weather_enabled=True)
    assert result.search is None
    assert news.get_news.await_args.kwargs["refresh"] is False
    assert not search.search.called and not weather.get_weather.called
    assert not location.resolve_location.called
    await coordinator.close()


@pytest.mark.anyio
async def test_news_preview_keeps_links_dates_and_staleness():
    from types import SimpleNamespace
    from apps.backend.app.api.routes.environment import get_environment_news
    news = AsyncMock()
    article = NewsArticle("NASA discovery", "NASA", "Science", "2026-09-30T00:00:00+00:00",
                          "science", "https://www.nasa.gov/discovery/", True)
    news.get_news.return_value = NewsDigestSnapshot("science", (article,), 0, "2026-09-30T00:00:00+00:00", True, cached=True)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        situational_coordinator=SimpleNamespace(news_service=news),
        runtime_settings=SimpleNamespace(news_category="science"))))
    result = await get_environment_news(request)
    assert result["stale"] and result["cached"]
    assert result["updated_at"] == article.published
    assert result["articles"][0]["url"] == article.url


@pytest.mark.anyio
async def test_disabling_background_skips_queued_feeds(monkeypatch):
    monkeypatch.setattr(news_module, "FEEDS", {"general": [(str(i), f"https://example.com/{i}") for i in range(8)]})
    enabled = True
    calls, release = [], asyncio.Event()
    async def handler(r):
        calls.append(r)
        await release.wait()
        return httpx.Response(500)
    service = NewsService(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    service.start_background(lambda: enabled)
    await asyncio.sleep(0.01)
    assert len(calls) == 4
    enabled = False
    release.set()
    await asyncio.sleep(0.01)
    try:
        assert len(calls) == 4
    finally:
        await service.close()


def test_page_listing_event_times_are_not_article_publication_dates():
    parser = _ArticleParser()
    parser.feed('<time datetime="2026-10-08">Upcoming Python event</time>'
                '<meta property="article:published_time" content="2026-09-01">'
                '<meta property="article:modified_time" content="2026-10-01">'
                '<p>Python release documentation.</p>')
    _, published = parser.evidence("Python release")
    assert published.startswith("2026-09-01")
    assert parser.modified == ["2026-10-01"]

@pytest.mark.anyio
async def test_news_yesterday_uses_host_timezone_and_keeps_period_in_fallback():
    from types import SimpleNamespace
    news, search = AsyncMock(), AsyncMock()
    news.get_news.return_value = NewsDigestSnapshot("all", (), 0)
    search.search.return_value = SearchService._snapshot("GTA VI", status="empty")
    local_time = SimpleNamespace(now=lambda: SimpleNamespace(iso_timestamp="2026-10-01T00:30:00+03:00"))
    coordinator = SituationalCoordinator(time_service=local_time, news_service=news, search_service=search)
    result = await coordinator.resolve_enrichment("новости GTA VI за вчера", weather_enabled=False)
    options = news.get_news.await_args.kwargs
    assert options["since"].astimezone(UTC).isoformat() == "2026-09-29T21:00:00+00:00"
    assert options["until"].astimezone(UTC).isoformat() == "2026-09-30T21:00:00+00:00"
    assert "вчера" in search.search.await_args.args[0]
    assert result.search.status == "empty"
    await coordinator.close()

@pytest.mark.anyio
@pytest.mark.parametrize("query", ["новости test@example.com", "найди +7 (999) 123-45-67", "api_key=secretvalue", r"новости D:\Private\notes"])
async def test_private_identifiers_are_not_sent_to_search_providers(query):
    calls = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    service = SearchService(client)
    try:
        snapshot = await service.search(query)
        assert snapshot.status == "invalid"
        assert not calls
    finally:
        await service.close()
