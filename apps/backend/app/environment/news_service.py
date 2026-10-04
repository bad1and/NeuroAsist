"""Curated RSS/Atom retrieval with per-source caching and bounded foreground work."""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
import logging
import re
import time
import xml.etree.ElementTree as ET

import httpx

from apps.backend.app.environment.retrieval import canonical_url, clean_text, model_text, normalize_entity, parse_date, relevance

logger = logging.getLogger(__name__)
FEEDS: dict[str, list[tuple[str, str]]] = {
    "general": [
        ("Google News", "https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru"),
        ("РБК", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
        ("Лента", "https://lenta.ru/rss/news"),
        ("Коммерсантъ", "https://www.kommersant.ru/RSS/news.xml"),
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ],
    "tech": [
        ("Хабр", "https://habr.com/ru/rss/hubs/all/"),
        ("3DNews", "https://3dnews.ru/news/rss/"),
        ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("TechCrunch", "https://techcrunch.com/feed/"),
    ],
    "science": [
        ("N+1", "https://nplus1.ru/rss"),
        ("NASA", "https://www.nasa.gov/feed/"),
        ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml"),
    ],
    "games": [
        ("DTF", "https://dtf.ru/rss"),
        ("IGN", "https://feeds.feedburner.com/ign/all"),
        ("Чемпионат", "https://www.championat.com/rss/news/cybersport/"),
        ("PC Gamer", "https://www.pcgamer.com/rss/"),
    ],
}
NEWS_CATEGORIES = ("all", *FEEDS)


def _clean_text(raw_text: str | None, max_len: int = 200) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", raw_text or ""), max_len)


@dataclass(frozen=True, slots=True)
class NewsArticle:
    title: str
    source: str
    snippet: str
    published: str
    category: str
    url: str = ""
    stale: bool = False


@dataclass(frozen=True, slots=True)
class NewsDigestSnapshot:
    category: str
    articles: tuple[NewsArticle, ...]
    cached_at: float
    updated_at: str = ""
    stale: bool = False
    query: str = ""
    cached: bool = False
    since: str = ""
    until: str = ""
    shown_urls: tuple[str, ...] = ()
    shown_titles: tuple[str, ...] = ()
    has_more: bool = False
    source_health: tuple[dict[str, object], ...] = ()

    def compact_summary(self, max_items: int = 5, max_chars: int = 900) -> str:
        if not self.articles:
            return "Свежие новости по этой теме сейчас недоступны."
        heading = f"Главные новости ({self.category}, обновлено {self.updated_at[:16]}):"
        if self.stale:
            heading += " [кэш устарел; обновление не удалось]"
        lines = [heading]
        remaining = max_chars - len(heading) - 1
        for i, article in enumerate(self.articles[:max_items]):
            slots = min(max_items, len(self.articles)) - i
            budget = max(0, remaining // slots - 1)
            date = f" {article.published[:10]}" if article.published else " дата неизвестна"
            prefix = f"• [{article.source}]{date} "
            title = model_text(article.title, max(0, min(140, budget - len(prefix))))
            line = prefix + title
            room = budget - len(line) - 3
            if room > 25 and article.snippet and article.snippet != article.title:
                line += " — " + model_text(article.snippet, min(100, room))
            lines.append(line[:budget])
            remaining -= len(lines[-1]) + 1
        return "\n".join(lines)[:max_chars]

    def metadata(self) -> dict[str, object]:
        return {
            "query": self.query or f"Новости: {self.category}", "category": self.category,
            "updated_at": self.updated_at, "searched_at": self.updated_at,
            "provider": "rss", "status": "ok" if self.articles else "empty",
            "cached": self.cached, "stale": self.stale,
            "topic": self.query, "since": self.since, "until": self.until,
            "shown_urls": list(self.shown_urls), "shown_titles": list(self.shown_titles),
            "has_more": self.has_more, "source_health": list(self.source_health),
            "sources": [{"title": a.title, "url": a.url, "published_at": a.published,
                         "source": a.source, "stale": a.stale,
                         "summary": model_text(a.snippet, 600)} for a in self.articles if a.url],
        }


class NewsService:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._sources: dict[str, tuple[tuple[NewsArticle, ...], float, str]] = {}
        self._inflight: dict[str, asyncio.Task[None]] = {}
        self._retry_after: dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(4)
        self._cache_ttl_seconds = 900
        self._stale_seconds = 7200
        self._foreground_timeout = 2.2
        self._background_task: asyncio.Task[None] | None = None
        self._background_enabled = None
        self._closed = False
        self._health: dict[str, dict[str, object]] = {}

    async def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=2.0, follow_redirects=True)
        return self._client

    def start_background(self, enabled) -> None:
        """Start after text readiness; the callback reads current runtime settings."""
        if self._background_task is None and not self._closed:
            self._background_enabled = enabled
            self._background_task = asyncio.create_task(self._background(enabled), name="environment:news")

    async def _background(self, enabled):
        while True:
            if enabled():
                await self.refresh(background=True)
            # Check toggles promptly; source TTL still limits actual downloads.
            await asyncio.sleep(30)

    async def close(self):
        self._closed = True
        tasks = [*self._inflight.values()]
        if self._background_task:
            tasks.append(self._background_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._background_task = None
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _schedule(self, category="all", *, background=False):
        tasks = []
        now = time.monotonic()
        for cat, feeds in FEEDS.items():
            if category != "all" and cat != category:
                continue
            for name, url in feeds:
                entry = self._sources.get(url)
                if entry and now - entry[1] < self._cache_ttl_seconds:
                    continue
                if self._retry_after.get(url, 0) > now or self._closed:
                    continue
                task = self._inflight.get(url)
                if task is None:
                    task = asyncio.create_task(self._refresh_source(cat, name, url, background=background))
                    self._inflight[url] = task
                    def remove(done, key=url):
                        if self._inflight.get(key) is done:
                            self._inflight.pop(key, None)
                    task.add_done_callback(remove)
                tasks.append(task)
        return tasks

    async def refresh(self, category="all", *, background=False):
        tasks = self._schedule(category, background=background)
        if tasks:
            await asyncio.gather(*(asyncio.shield(t) for t in tasks))

    async def _refresh_source(self, category, source, url, *, background=False):
        try:
            async with self._semaphore:
                if background and self._background_enabled is not None and not self._background_enabled():
                    return
                async with asyncio.timeout(2.0):
                    client = await self._get_client()
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        content = bytearray()
                        async for chunk in resp.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > 2_000_000:
                                raise ValueError("Feed too large")
                    articles = self._parse_feed(bytes(content), category, source)
            if articles:
                self._sources[url] = (articles, time.monotonic(), datetime.now(UTC).isoformat())
                self._retry_after.pop(url, None)
                self._health[url] = {"source": source, "status": "ok", "articles_count": len(articles),
                                     "updated_at": self._sources[url][2]}
            else:
                self._retry_after[url] = time.monotonic() + 30
                self._health[url] = {"source": source, "status": "empty", "articles_count": 0}
        except (httpx.HTTPError, TimeoutError, ValueError, ET.ParseError) as exc:
            self._retry_after[url] = time.monotonic() + 30
            self._health[url] = {"source": source, "status": "timeout" if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else "error",
                                 "articles_count": len(self._sources.get(url, ((),))[0]),
                                 "updated_at": self._sources.get(url, ((), 0, ""))[2]}
            logger.debug("RSS source %s unavailable: %s", source, type(exc).__name__)

    @staticmethod
    def _parse_feed(content, category, source):
        root = ET.fromstring(content)
        atom = "{http://www.w3.org/2005/Atom}"
        items = root.findall(".//item") or root.findall(f".//{atom}entry")
        articles = []
        for item in items[:60]:
            is_atom = item.tag.startswith(atom)
            prefix = atom if is_atom else ""
            title = _clean_text(item.findtext(prefix + "title"), 140)
            if not title:
                continue
            description = (item.findtext(prefix + ("summary" if is_atom else "description"))
                           or item.findtext(prefix + "content") or "")
            link = item.findtext("link") or ""
            if is_atom:
                links = item.findall(atom + "link")
                link = next((a.get("href", "") for a in links if a.get("rel", "alternate") == "alternate"), "")
            date = parse_date(item.findtext(prefix + ("published" if is_atom else "pubDate"))
                              or item.findtext(prefix + "updated") or "")
            articles.append(NewsArticle(title, source, _clean_text(description, 160),
                date.isoformat() if date else "", category, canonical_url(link)))
        return tuple(articles)

    async def get_news(self, category="all", max_articles=6, *, query="", since=None, until=None, refresh=True,
                       exclude_urls=(), exclude_titles=(), deadline=None):
        category = category.lower().strip()
        if category not in NEWS_CATEGORIES:
            category = "all"
        # Topic searches consider every category, e.g. a game story in a general feed.
        selection_category = "all" if query else category
        tasks = self._schedule(selection_category) if refresh else []
        was_cached = not tasks
        if tasks:
            # Pending source tasks continue warming the cache; no network wait
            # occurs under a shared lock, and cancellation cannot strand a lock.
            remaining = max(0, deadline - time.monotonic()) if deadline is not None else self._foreground_timeout
            await asyncio.wait(tasks, timeout=min(self._foreground_timeout, remaining))
        now, wall = time.monotonic(), datetime.now(UTC)
        lower = parse_date(since) if isinstance(since, str) else since
        upper = parse_date(until) if isinstance(until, str) else until
        lower = lower or (wall - timedelta(hours=48))
        upper = upper or (wall + timedelta(minutes=5))
        candidates, updates = [], []
        for cat, feeds in FEEDS.items():
            if selection_category != "all" and cat != selection_category:
                continue
            for _, url in feeds:
                entry = self._sources.get(url)
                if not entry or now - entry[1] > self._stale_seconds:
                    continue
                articles, timestamp, updated = entry
                stale = now - timestamp >= self._cache_ttl_seconds
                updates.append(updated)
                for a in articles:
                    published = parse_date(a.published)
                    if published is None or not lower <= published < upper:
                        continue
                    if query and not relevance(query, a.title + " " + a.snippet):
                        continue
                    candidates.append((a, stale))
        candidates.sort(key=lambda pair: (
            -(relevance(query, pair[0].title + " " + pair[0].snippet) if query else 0),
            -parse_date(pair[0].published).timestamp(), pair[0].source, pair[0].title))
        unique, urls, titles, title_index = [], set(), [], {}
        exact_titles = set()
        for article, stale in candidates:
            title = re.sub(r"[^\w]+", " ", normalize_entity(article.title)).strip()
            if article.url and article.url in urls:
                continue
            if title in exact_titles:
                continue
            tokens = set(title.split())
            possible = Counter(i for token in tokens for i in title_index.get(token, ()))
            numbers = set(re.findall(r"\d+", title))
            duplicate = any(
                overlap / max(len(tokens), len(titles[i][1])) >= 0.7
                and numbers == titles[i][2]
                and SequenceMatcher(None, title, titles[i][0]).ratio() >= 0.82
                for i, overlap in possible.items()
            )
            if duplicate:
                continue
            urls.add(article.url)
            exact_titles.add(title)
            index = len(titles)
            titles.append((title, tokens, numbers))
            for token in tokens:
                title_index.setdefault(token, []).append(index)
            unique.append(NewsArticle(article.title, article.source, article.snippet, article.published,
                                      article.category, article.url, stale))
        chosen, counts = [], Counter()
        limit = max(0, min(int(max_articles), 20))
        excluded = set(exclude_urls)
        old_titles = [normalize_entity(t) for t in exclude_titles]
        unique = [a for a in unique if a.url not in excluded and not any(
            SequenceMatcher(None, normalize_entity(a.title), t).ratio() >= 0.82
            and set(re.findall(r"\d+", a.title)) == set(re.findall(r"\d+", t)) for t in old_titles)]
        source_limit = max(2, (limit + max(1, len({a.source for a in unique})) - 1) // max(1, len({a.source for a in unique})))
        # First cover the available categories, then fill by freshness/relevance.
        if not query and category == "all":
            for cat in FEEDS:
                item = next((a for a in unique if a.category == cat and counts[a.source] < 2), None)
                if item and len(chosen) < limit:
                    chosen.append(item)
                    counts[item.source] += 1
        for article in unique:
            if len(chosen) >= limit:
                break
            if article not in chosen and counts[article.source] < source_limit:
                chosen.append(article)
                counts[article.source] += 1
        shown_urls = tuple(dict.fromkeys([*exclude_urls, *(a.url for a in chosen if a.url)]))[-200:]
        shown_titles = tuple(dict.fromkeys([*exclude_titles, *(a.title for a in chosen)]))[-200:]
        return NewsDigestSnapshot(category, tuple(chosen), now, max(updates, default=""),
                                  any(a.stale for a in chosen), query, was_cached,
                                  lower.isoformat(), upper.isoformat(), shown_urls, shown_titles,
                                  any(a not in chosen for a in unique), tuple(self._health.values()))
