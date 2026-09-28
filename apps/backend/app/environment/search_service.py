"""Bounded, key-free web search used by Iris during a conversation turn."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import html
from html.parser import HTMLParser
import logging
import re
import time
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_MAX_QUERY_CHARS = 300
_MAX_TITLE_CHARS = 120
_MAX_SNIPPET_CHARS = 300


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
    status: str = "ok"
    provider: str = "duckduckgo"
    cached: bool = False
    searched_at: str = ""

    def compact_summary(self, max_items: int = 3, max_chars: int = 1600) -> str:
        """Return bounded facts for the model; URLs stay in durable metadata."""
        lines = [f"Результаты поиска по запросу «{self.query}»:"]
        if self.answer:
            lines.append(f"Краткий ответ: {self.answer[:_MAX_SNIPPET_CHARS]}")
        for res in self.results[:max_items]:
            lines.append(f"• {res.title[:_MAX_TITLE_CHARS]}: {res.snippet[:_MAX_SNIPPET_CHARS]}")
        return "\n".join(lines)[:max_chars]

    def metadata(self) -> dict[str, object]:
        return {
            "query": self.query,
            "searched_at": self.searched_at,
            "provider": self.provider,
            "status": self.status,
            "cached": self.cached,
            "sources": [
                {"title": item.title, "url": item.url}
                for item in self.results
                if item.url
            ],
        }


class _DuckDuckGoHTMLParser(HTMLParser):
    """Extract result links and snippets without adding an HTML dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture: str | None = None
        self._href = ""
        self._text: list[str] = []
        self._pending: list[tuple[str, str]] = []
        self.results: list[SearchResult] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if "result__a" in classes:
            self._capture, self._href, self._text = "title", values.get("href", ""), []
        elif "result__snippet" in classes:
            self._capture, self._text = "snippet", []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._capture:
            return
        value = _clean_text("".join(self._text))
        if self._capture == "title" and value:
            self._pending.append((value[:_MAX_TITLE_CHARS], _unwrap_ddg_url(self._href)))
        elif self._capture == "snippet" and value and self._pending:
            title, url = self._pending.pop(0)
            self.results.append(SearchResult(title, value[:_MAX_SNIPPET_CHARS], url))
        self._capture, self._href, self._text = None, "", []


def _clean_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", html.unescape(value)).strip()


def _unwrap_ddg_url(value: str) -> str:
    decoded = html.unescape(value).strip()
    if decoded.startswith("//"):
        decoded = f"https:{decoded}"
    parsed = urllib.parse.urlparse(decoded)
    if parsed.netloc.endswith("duckduckgo.com"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            decoded = urllib.parse.unquote(target)
    parsed = urllib.parse.urlparse(decoded)
    return decoded if parsed.scheme in {"http", "https"} and parsed.netloc else ""


class SearchService:
    """DuckDuckGo lookup with bounded latency, cache and request coalescing."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._cache_lock = asyncio.Lock()
        self._cache: OrderedDict[str, tuple[SearchSnapshot, float]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[SearchSnapshot]] = {}
        self._inflight_waiters: dict[str, int] = {}
        self._cache_ttl_seconds = 5 * 60
        self._cache_max_entries = 256

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=5.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
        return self._client

    async def close(self) -> None:
        tasks = tuple(self._inflight.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._inflight_waiters.clear()
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def search(self, query: str) -> SearchSnapshot:
        clean_q = _clean_text(query)[:_MAX_QUERY_CHARS]
        if not clean_q:
            return self._snapshot("", status="empty")
        norm_q = clean_q.casefold()
        now = time.monotonic()
        async with self._cache_lock:
            cached_entry = self._cache.get(norm_q)
            if cached_entry is not None:
                snapshot, timestamp = cached_entry
                if now - timestamp < self._cache_ttl_seconds:
                    self._cache.move_to_end(norm_q)
                    return replace(snapshot, cached=True)
                self._cache.pop(norm_q, None)
            task = self._inflight.get(norm_q)
            if task is None:
                task = asyncio.create_task(self._perform_search(clean_q))
                self._inflight[norm_q] = task
                self._inflight_waiters[norm_q] = 0
            self._inflight_waiters[norm_q] = self._inflight_waiters.get(norm_q, 0) + 1

        try:
            snapshot = await asyncio.shield(task)
        except asyncio.CancelledError:
            async with self._cache_lock:
                remaining = self._inflight_waiters.get(norm_q, 1) - 1
                if remaining <= 0:
                    self._inflight_waiters.pop(norm_q, None)
                    self._inflight.pop(norm_q, None)
                    if not task.done():
                        task.cancel()
                else:
                    self._inflight_waiters[norm_q] = remaining
            raise
        else:
            async with self._cache_lock:
                remaining = self._inflight_waiters.get(norm_q, 1) - 1
                if remaining <= 0:
                    self._inflight_waiters.pop(norm_q, None)
                    if self._inflight.get(norm_q) is task:
                        self._inflight.pop(norm_q, None)
                else:
                    self._inflight_waiters[norm_q] = remaining

        if snapshot.status == "ok" and (snapshot.answer or snapshot.results):
            async with self._cache_lock:
                self._cache[norm_q] = (snapshot, time.monotonic())
                self._cache.move_to_end(norm_q)
                while len(self._cache) > self._cache_max_entries:
                    self._cache.popitem(last=False)
        return snapshot

    async def _perform_search(self, query: str) -> SearchSnapshot:
        try:
            async with asyncio.timeout(5.0):
                client = await self._get_client()
                answer: str | None = None
                results: list[SearchResult] = []
                try:
                    response = await client.get(
                        "https://api.duckduckgo.com/",
                        params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                    )
                    if response.status_code == 200:
                        data = response.json()
                        abstract = _clean_text(str(data.get("AbstractText") or ""))
                        if abstract:
                            answer = abstract[:_MAX_SNIPPET_CHARS]
                            url = _unwrap_ddg_url(str(data.get("AbstractURL") or ""))
                            heading = _clean_text(str(data.get("Heading") or query))
                            if url:
                                results.append(SearchResult(heading[:_MAX_TITLE_CHARS], answer, url))
                except (httpx.HTTPError, ValueError) as exc:
                    logger.debug("DuckDuckGo Instant Answer failed: %s", exc)

                if not results:
                    response = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
                    if response.status_code in {202, 403, 429}:
                        if answer:
                            return self._snapshot(query, answer=answer, status="ok")
                        return self._snapshot(query, status="blocked")
                    response.raise_for_status()
                    results = self._parse_ddg_html(response.text, max_items=3)
                status = "ok" if answer or results else "empty"
                return self._snapshot(query, results=results, answer=answer, status=status)
        except TimeoutError:
            return self._snapshot(query, status="timeout")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("DuckDuckGo search failed: %s", exc)
            return self._snapshot(query, status="error")

    @staticmethod
    def _snapshot(
        query: str,
        *,
        results: list[SearchResult] | None = None,
        answer: str | None = None,
        status: str,
    ) -> SearchSnapshot:
        return SearchSnapshot(
            query=query,
            results=tuple((results or [])[:3]),
            answer=answer,
            status=status,
            searched_at=datetime.now(UTC).isoformat(),
        )

    def _parse_ddg_html(self, html_text: str, max_items: int = 3) -> list[SearchResult]:
        parser = _DuckDuckGoHTMLParser()
        parser.feed(html_text)
        return parser.results[:max_items]
