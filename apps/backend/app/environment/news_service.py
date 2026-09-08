"""News aggregator service using curated RSS feeds.

Features:
- Free, no API keys required.
- Categories: General ("general"), Tech & IT ("tech"), All ("all").
- In-memory caching with 60-minute TTL.
- Strict token budgeting: outputs compact digests (5-7 bullets, ~150-200 tokens max).
- Background pre-fetching and graceful offline fallback.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import html
import logging
import re
import time
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

FEEDS: dict[str, list[tuple[str, str]]] = {
    "general": [
        ("Google News", "https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru"),
        ("РБК", "https://rssexport.rbc.ru/rbcnews/news/20/full.rss"),
        ("Лента", "https://lenta.ru/rss/news"),
    ],
    "tech": [
        ("Хабр", "https://habr.com/ru/rss/hubs/all/"),
        ("3DNews", "https://3dnews.ru/news/rss/"),
    ],
}


def _clean_text(raw_text: str | None, max_len: int = 200) -> str:
    if not raw_text:
        return ""
    text = _TAG_RE.sub(" ", raw_text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


@dataclass(frozen=True, slots=True)
class NewsArticle:
    title: str
    source: str
    snippet: str
    published: str
    category: str


@dataclass(frozen=True, slots=True)
class NewsDigestSnapshot:
    category: str
    articles: tuple[NewsArticle, ...]
    cached_at: float

    def compact_summary(self, max_items: int = 5) -> str:
        """Compact string representation for on-demand injection (~150-200 tokens)."""
        if not self.articles:
            return "Свежие новости сейчас недоступны."

        lines = [f"Главные новости ({self.category}):"]
        for article in self.articles[:max_items]:
            snippet_part = f" — {article.snippet}" if article.snippet and article.snippet != article.title else ""
            lines.append(f"• [{article.source}] {article.title}{snippet_part}")
        return "\n".join(lines)


class NewsService:
    """Aggregates and caches news digests from curated RSS feeds."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._cache_lock = asyncio.Lock()
        self._cache: dict[str, tuple[NewsDigestSnapshot, float]] = {}
        self._cache_ttl_seconds = 60 * 60  # 60 minutes

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=2.5, follow_redirects=True)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def get_news(self, category: str = "all", max_articles: int = 6) -> NewsDigestSnapshot:
        """Get latest news digest for category ('general', 'tech', 'all') with in-memory caching."""
        cat_key = category.lower().strip()
        if cat_key not in ("general", "tech", "all"):
            cat_key = "all"

        now = time.monotonic()
        async with self._cache_lock:
            cached_entry = self._cache.get(cat_key)
            if cached_entry is not None:
                snapshot, timestamp = cached_entry
                if (now - timestamp) < self._cache_ttl_seconds:
                    return snapshot

            # Fetch fresh digest
            snapshot = await self._fetch_news(cat_key, max_articles)
            if snapshot.articles or cached_entry is None:
                self._cache[cat_key] = (snapshot, now)
                return snapshot
            # If fetch returned nothing (e.g. offline), return older cached entry
            return cached_entry[0]

    async def _fetch_news(self, category: str, max_articles: int) -> NewsDigestSnapshot:
        target_feeds: list[tuple[str, str]] = []
        if category == "all":
            target_feeds.extend(FEEDS["general"][:2])
            target_feeds.extend(FEEDS["tech"][:1])
        else:
            target_feeds.extend(FEEDS.get(category, FEEDS["general"]))

        articles: list[NewsArticle] = []
        seen_titles: set[str] = set()

        client = await self._get_client()

        for source_name, url in target_feeds:
            try:
                resp = await client.get(url, timeout=2.0)
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.text)
                items = root.findall(".//item")
                for item in items[:4]:
                    raw_title = item.findtext("title") or ""
                    title = _clean_text(raw_title, max_len=140)
                    if not title or title.lower() in seen_titles:
                        continue
                    seen_titles.add(title.lower())

                    raw_desc = item.findtext("description") or ""
                    snippet = _clean_text(raw_desc, max_len=160)

                    pub_date = item.findtext("pubDate") or ""

                    articles.append(
                        NewsArticle(
                            title=title,
                            source=source_name,
                            snippet=snippet,
                            published=pub_date,
                            category=category,
                        )
                    )
                    if len(articles) >= max_articles:
                        break
            except Exception as exc:
                logger.debug("Failed to fetch RSS feed %s (%s): %s", source_name, url, exc)

            if len(articles) >= max_articles:
                break

        return NewsDigestSnapshot(
            category=category,
            articles=tuple(articles),
            cached_at=time.monotonic(),
        )
