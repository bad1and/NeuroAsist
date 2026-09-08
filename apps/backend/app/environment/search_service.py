"""Lightweight on-demand web search and fact lookup service.

Provides instant answers and web search snippets without requiring API keys.
Used only on-demand when user explicitly asks for external fact lookups.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import html
import logging
import re
import time
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    snippet: str
    url: str


@dataclass(frozen=True, slots=True)
class SearchSnapshot:
    query: str
    results: tuple[SearchResult, ...]
    answer: str | None = None

    def compact_summary(self, max_items: int = 3) -> str:
        """Compact string representation for on-demand injection (~120 tokens)."""
        lines = [f"Результаты поиска по запросу «{self.query}»:"]
        if self.answer:
            lines.append(f"Краткий ответ: {self.answer}")
        for res in self.results[:max_items]:
            lines.append(f"• {res.title}: {res.snippet}")
        return "\n".join(lines)


class SearchService:
    """Fast DuckDuckGo search for on-demand factual lookups."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._cache_lock = asyncio.Lock()
        self._cache: dict[str, tuple[SearchSnapshot, float]] = {}
        self._cache_ttl_seconds = 30 * 60  # 30 minutes

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=2.5,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def search(self, query: str) -> SearchSnapshot | None:
        clean_q = query.strip()
        if not clean_q:
            return None

        norm_q = clean_q.lower()
        now = time.monotonic()

        async with self._cache_lock:
            cached_entry = self._cache.get(norm_q)
            if cached_entry is not None:
                snapshot, timestamp = cached_entry
                if (now - timestamp) < self._cache_ttl_seconds:
                    return snapshot

            # 1. Try DuckDuckGo Instant Answer API
            client = await self._get_client()
            answer_text = None
            results: list[SearchResult] = []

            try:
                api_resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": clean_q, "format": "json", "no_html": "1", "skip_disambig": "1"},
                    timeout=2.0,
                )
                if api_resp.status_code == 200:
                    data = api_resp.json()
                    abstract = data.get("AbstractText")
                    if abstract:
                        answer_text = str(abstract)[:300]
                    related = data.get("RelatedTopics", [])
                    for topic in related[:3]:
                        if isinstance(topic, dict) and "Text" in topic:
                            text = topic["Text"]
                            results.append(SearchResult(title=clean_q, snippet=text[:200], url=""))
            except Exception as exc:
                logger.debug("DuckDuckGo Instant Answer failed: %s", exc)

            # 2. If no instant answer, try HTML search
            if not answer_text and not results:
                try:
                    html_resp = await client.post(
                        "https://html.duckduckgo.com/html/",
                        data={"q": clean_q},
                        timeout=2.0,
                    )
                    if html_resp.status_code == 200:
                        results = self._parse_ddg_html(html_resp.text, max_items=3)
                except Exception as exc:
                    logger.debug("DuckDuckGo HTML search failed: %s", exc)

            snapshot = SearchSnapshot(
                query=clean_q,
                results=tuple(results),
                answer=answer_text,
            )
            self._cache[norm_q] = (snapshot, now)
            return snapshot

    def _parse_ddg_html(self, html_text: str, max_items: int = 3) -> list[SearchResult]:
        results: list[SearchResult] = []
        snippets = re.findall(
            r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        titles = re.findall(
            r'<a class="result__url[^"]*"[^>]*>(.*?)</a>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )

        for i in range(min(len(snippets), max_items)):
            snippet_raw = snippets[i]
            clean_snip = _TAG_RE.sub("", snippet_raw)
            clean_snip = html.unescape(clean_snip)
            clean_snip = _WHITESPACE_RE.sub(" ", clean_snip).strip()
            title = titles[i] if i < len(titles) else "Поиск"
            clean_title = html.unescape(_TAG_RE.sub("", title)).strip()
            if clean_snip:
                results.append(SearchResult(title=clean_title or "Найдено", snippet=clean_snip[:200], url=""))
        return results
