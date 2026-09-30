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
import socket
import ipaddress
import json
import xml.etree.ElementTree as ET

import httpx

from apps.backend.app.environment.retrieval import canonical_url, clean_text, model_text, parse_date, preferred_host, relevance, sensitive_query

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
    published_at: str = ""
    page_text: str = ""
    page_status: str = "not_read"
    provider: str = "duckduckgo"
    modified_at: str = ""


@dataclass(frozen=True, slots=True)
class SearchSnapshot:
    query: str
    results: tuple[SearchResult, ...]
    answer: str | None = None
    status: str = "ok"
    provider: str = "duckduckgo"
    cached: bool = False
    searched_at: str = ""
    attempts: tuple[dict[str, object], ...] = ()
    latency_ms: int = 0

    def compact_summary(self, max_items: int = 3, max_chars: int = 1600) -> str:
        """Return bounded facts for the model; URLs stay in durable metadata."""
        lines = [f"Результаты поиска по запросу «{model_text(self.query, 300)}»:"]
        if self.answer:
            lines.append(f"Краткий ответ: {self.answer[:_MAX_SNIPPET_CHARS]}")
        for res in self.results[:max_items]:
            date = f" ({res.published_at[:10]})" if res.published_at else ""
            evidence = res.page_text or res.snippet
            limit = 600 if res.page_text else _MAX_SNIPPET_CHARS
            limitation = " [только поисковый сниппет]" if res.page_status != "read" else ""
            if not res.published_at and re.search(r"новост|\bnews\b", self.query, re.I):
                limitation += " [дата публикации неизвестна]"
            lines.append(f"• {model_text(res.title, _MAX_TITLE_CHARS)}{date}: {model_text(evidence, limit)}{limitation}")
        return "\n".join(lines)[:max_chars]

    def metadata(self) -> dict[str, object]:
        return {
            "query": self.query,
            "searched_at": self.searched_at,
            "provider": self.provider,
            "status": self.status,
            "cached": self.cached,
            "attempts": list(self.attempts),
            "latency_ms": self.latency_ms,
            "sources": [
                {"title": item.title, "url": item.url, "published_at": item.published_at,
                 "page_status": item.page_status, "provider": item.provider, "modified_at": item.modified_at}
                for item in self.results
                if item.url
            ],
        }


class _DuckDuckGoHTMLParser(HTMLParser):
    """Extract result links and snippets without adding an HTML dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture: str | None = None
        self._capture_tag = ""
        self._href = ""
        self._text: list[str] = []
        self._pending: list[tuple[str, str]] = []
        self.results: list[SearchResult] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if "result__a" in classes and tag == "a":
            self._capture, self._href, self._text = "title", values.get("href", ""), []
            self._capture_tag = tag
        elif "result__snippet" in classes:
            self._capture, self._text = "snippet", []
            self._capture_tag = tag

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._capture_tag or not self._capture:
            return
        value = _clean_text("".join(self._text))
        if self._capture == "title" and value:
            if self._pending:
                title, url = self._pending.pop()
                self.results.append(SearchResult(title, "", url))
            self._pending.append((value[:_MAX_TITLE_CHARS], _unwrap_ddg_url(self._href)))
        elif self._capture == "snippet" and value and self._pending:
            title, url = self._pending.pop()
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



class _ArticleParser(HTMLParser):
    """Collect paragraphs and publication metadata without executing page code."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.paragraphs, self.current, self.dates, self.ld = [], [], [], [], []
        self.capture, self.description, self.ld_capture = None, "", False
        self.modified, self.article_depth = [], 0
        self.skips = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "article":
            self.article_depth += 1
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in {"article:published_time", "date", "datepublished"}:
                self.dates.append(a.get("content", ""))
            if key in {"article:modified_time", "datemodified"}:
                self.modified.append(a.get("content", ""))
            if key in {"description", "og:description"}:
                self.description = a.get("content", "")
        if tag == "time" and a.get("datetime") and (self.article_depth or a.get("itemprop") == "datePublished"):
            self.dates.append(a["datetime"])
        if tag in self.skips or self.stack:
            if tag not in {"meta", "link", "img", "br", "input", "hr", "source"}:
                self.stack.append(tag)
            if tag == "script" and a.get("type") == "application/ld+json":
                self.ld_capture = True
                self.ld.append("")
            return
        if tag in {"p", "h1", "h2", "h3"}:
            self.capture, self.current = tag, []

    def handle_endtag(self, tag):
        if tag == "article":
            self.article_depth = max(0, self.article_depth - 1)
        if self.stack:
            if tag in self.stack:
                index = len(self.stack) - 1 - self.stack[::-1].index(tag)
                del self.stack[index:]
            if tag == "script":
                self.ld_capture = False
            return
        if tag == self.capture:
            text = clean_text(" ".join(self.current), 1600)
            if len(text) >= 20:
                self.paragraphs.append(text)
            self.capture, self.current = None, []

    def handle_data(self, data):
        if self.ld_capture and self.ld:
            self.ld[-1] += data
        elif self.capture and not self.stack:
            self.current.append(data)

    def evidence(self, query):
        for raw in self.ld[:8]:
            try:
                obj = json.loads(raw)
            except (ValueError, TypeError):
                continue
            queue = [obj]
            for _ in range(100):
                if not queue:
                    break
                item = queue.pop()
                if isinstance(item, list):
                    queue.extend(item[:20])
                elif isinstance(item, dict):
                    if "datePublished" in item:
                        self.dates.append(str(item["datePublished"]))
                    if "dateModified" in item:
                        self.modified.append(str(item["dateModified"]))
                    body = item.get("articleBody")
                    if isinstance(body, str):
                        self.paragraphs.append(clean_text(body, 4000))
                    queue.extend(v for v in item.values() if isinstance(v, (dict, list)))
        paragraphs = self.paragraphs or ([self.description] if self.description else [])
        paragraphs = sorted(enumerate(paragraphs), key=lambda x: (-relevance(query, x[1]), x[0]))
        text = model_text(" ".join(p for _, p in paragraphs[:4]), 1800)
        dates = [d for v in self.dates if (d := parse_date(v)) is not None]
        return text, max(dates).isoformat() if dates else ""


async def _public_address(host: str, port: int) -> str:
    """Resolve once and pin a public address, avoiding a second DNS resolution."""
    addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = [ipaddress.ip_address(info[4][0]) for info in addresses]
    if not ips or any(not ip.is_global for ip in ips):
        raise ValueError("Non-public page address")
    return str(ips[0])


async def _read_public_page(client: httpx.AsyncClient, url: str, max_bytes: int = 512_000) -> bytes:
    for _ in range(4):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid page URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in {80, 443}:
            raise ValueError("Unsupported page port")
        address = await _public_address(parsed.hostname, port)
        pinned = httpx.URL(url).copy_with(host=address)
        async with client.stream("GET", pinned, headers={"Host": parsed.netloc, "Connection": "close"},
                                 extensions={"sni_hostname": parsed.hostname}, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                target = response.headers.get("location")
                if not target:
                    raise ValueError("Redirect without location")
                url = urllib.parse.urljoin(url, target)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "text/html")
            if not any(t in content_type for t in ("text/html", "application/xhtml+xml", "text/plain")):
                raise ValueError("Unsupported page format")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ValueError("Page too large")
            return bytes(content)
    raise ValueError("Too many redirects")


_MONTH_NAMES = (
    ("января", "january"), ("февраля", "february"), ("марта", "march"),
    ("апреля", "april"), ("мая", "may"), ("июня", "june"),
    ("июля", "july"), ("августа", "august"), ("сентября", "september"),
    ("октября", "october"), ("ноября", "november"), ("декабря", "december"),
)
_MONTH_NUMBER = {name: index for index, names in enumerate(_MONTH_NAMES, 1) for name in names}
_DATE_CLAIM = re.compile(
    r"\b(?:(?P<day>\d{1,2})\s+(?P<month>" + "|".join(_MONTH_NUMBER) +
    r")\s+(?P<year>20\d{2})|(?P<en_month>" + "|".join(_MONTH_NUMBER) +
    r")\s+(?P<en_day>\d{1,2}),?\s+(?P<en_year>20\d{2}))\b", re.I,
)


def _conflicting_date_claims(results):
    """Same-year postponements are conflicts too, not just differing years."""
    claims = set()
    for result in results:
        text = result.title + " " + result.snippet
        for match in _DATE_CLAIM.finditer(text):
            claims.add((int(match["year"] or match["en_year"]),
                        _MONTH_NUMBER[(match["month"] or match["en_month"]).lower()],
                        int(match["day"] or match["en_day"])))
        for year, month, day in re.findall(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text):
            claims.add((int(year), int(month), int(day)))
    return len(claims) > 1


class SearchService:
    """Two search providers and optional page evidence under one deadline."""
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._page_client = http_client
        self._cache_lock = asyncio.Lock()
        self._cache = OrderedDict()
        self._inflight, self._inflight_waiters, self._blocked_until = {}, {}, {}
        self._cache_ttl_seconds, self._error_ttl_seconds = 300, 30
        self._cache_max_entries, self._deadline_seconds = 256, 5.0

    async def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=2.0, follow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        return self._client

    async def close(self):
        tasks = tuple(self._inflight.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._inflight_waiters.clear()
        for client in {c for c in (self._client, self._page_client) if c is not None}:
            await client.aclose()
        self._client = self._page_client = None

    async def search(self, query: str, *, fallback_query: str | None = None,
                     preferred_domains: tuple[str, ...] = ()) -> SearchSnapshot:
        clean_q = clean_text(query, 300)
        fallback = clean_text(fallback_query or "", 300)
        domains = tuple(sorted({d.lower().strip().removeprefix("www.") for d in preferred_domains
            if isinstance(d, str) and re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", d.strip())}))[:3]
        if not clean_q:
            return self._snapshot("", status="empty")
        if sensitive_query(clean_q) or sensitive_query(fallback):
            return self._snapshot(clean_q, status="invalid")
        key = (clean_q.casefold(), fallback.casefold(), domains)
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry:
                snap, timestamp = entry
                ttl = self._cache_ttl_seconds if snap.status == "ok" else self._error_ttl_seconds
                if time.monotonic() - timestamp < ttl:
                    self._cache.move_to_end(key)
                    return replace(snap, cached=True, latency_ms=0)
                self._cache.pop(key, None)
            task = self._inflight.get(key)
            if task is None:
                async def run():
                    snap = await (self._perform_search(clean_q, fallback, domains) if fallback or domains else self._perform_search(clean_q))
                    async with self._cache_lock:
                        self._cache[key] = (snap, time.monotonic())
                        self._cache.move_to_end(key)
                        while len(self._cache) > self._cache_max_entries:
                            self._cache.popitem(last=False)
                    return snap
                task = asyncio.create_task(run())
                self._inflight[key], self._inflight_waiters[key] = task, 0
            self._inflight_waiters[key] += 1
        try:
            return await asyncio.shield(task)
        finally:
            async with self._cache_lock:
                remaining = self._inflight_waiters.get(key, 1) - 1
                if remaining <= 0:
                    self._inflight_waiters.pop(key, None)
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)
                    if not task.done():
                        task.cancel()
                else:
                    self._inflight_waiters[key] = remaining

    async def _provider(self, provider, query):
        if self._blocked_until.get(provider, 0) > time.monotonic():
            return [], "cooldown"
        client = await self._get_client()
        try:
            async with asyncio.timeout(1.25):
                if provider == "duckduckgo":
                    response = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
                else:
                    response = await client.get("https://www.bing.com/search", params={"q": query, "format": "rss"})
            lower = response.text.lower()
            if response.status_code in {202, 403, 429} or any(s in lower for s in ("anomaly-modal", "verify you are human", "smartcaptcha")):
                self._blocked_until[provider] = time.monotonic() + 60
                return [], "blocked"
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                return [], "error"
            if provider == "duckduckgo":
                results = self._parse_ddg_html(response.text, 8)
            else:
                root = ET.fromstring(response.content)
                results = [SearchResult(clean_text(i.findtext("title") or "", 120),
                    clean_text(i.findtext("description") or "", 300), canonical_url(i.findtext("link") or ""),
                    provider="bing") for i in root.findall(".//item")[:8]]
            results = [replace(r, url=canonical_url(r.url)) for r in results if canonical_url(r.url)]
            return results, "ok" if results else "empty"
        except (TimeoutError, httpx.TimeoutException):
            return [], "timeout"
        except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
            logger.debug("Search provider %s failed: %s", provider, exc)
            return [], "error"

    def _rank(self, query, results, domains):
        scored, seen = [], set()
        for item in results:
            score = relevance(query, item.title + " " + item.snippet + " " + (urllib.parse.urlsplit(item.url).hostname or ""))
            if not score or not item.url or item.url in seen:
                continue
            seen.add(item.url)
            score += 1.0 if preferred_host(item.url, domains) else 0
            scored.append((score, item))
        scored.sort(key=lambda x: (-x[0], -(parse_date(x[1].published_at).timestamp() if parse_date(x[1].published_at) else 0)))
        return [r for _, r in scored[:3]]

    async def _page(self, result, query):
        try:
            if self._page_client is None or self._page_client.is_closed:
                self._page_client = httpx.AsyncClient(timeout=1.7, trust_env=False)
            async with asyncio.timeout(1.7):
                content = await _read_public_page(self._page_client, result.url)
            parser = _ArticleParser()
            parser.feed(content.decode("utf-8", errors="replace"))
            text, date = parser.evidence(query)
            if text and not relevance(query, result.title + " " + text):
                text = ""
            modified = [d for v in parser.modified if (d := parse_date(v)) is not None]
            return replace(result, page_text=text, published_at=date,
                           modified_at=max(modified).isoformat() if modified else "",
                           page_status="read" if text else "unavailable")
        except (TimeoutError, httpx.HTTPError, ValueError, OSError):
            return replace(result, page_status="unavailable")

    async def _perform_search(self, query, fallback_query=None, preferred_domains=()):
        start = time.monotonic()
        attempts, candidates, ranked = [], [], []
        providers = [("duckduckgo", query), ("bing", query)]
        if fallback_query and fallback_query.casefold() != query.casefold():
            providers.append(("refine", fallback_query))
        elif preferred_domains:
            providers.append(("duckduckgo", query + " site:" + preferred_domains[0]))
        else:
            suffix = " официальный источник" if re.search(r"[а-яё]", query, re.I) else " official source"
            refined = query[:300 - len(suffix)] + suffix
            if refined != query:
                providers.append(("refine", refined))
        refinement_query = providers[2][1] if len(providers) == 3 else None
        try:
            async with asyncio.timeout(self._deadline_seconds):
                for attempt_index in range(min(3, len(providers))):
                    provider, actual_query = providers[attempt_index]
                    if provider == "refine":
                        provider = "bing" if self._blocked_until.get("duckduckgo", 0) > time.monotonic() else "duckduckgo"
                    t = time.monotonic()
                    results, status = await self._provider(provider, actual_query)
                    if attempt_index > 0 and actual_query == refinement_query and _conflicting_date_claims(ranked):
                        # On equal relevance, the focused clarification precedes
                        # the broad results that prompted the conflict.
                        candidates = [*results, *candidates]
                    else:
                        candidates.extend(results)
                    ranked = self._rank(query, candidates, preferred_domains)
                    attempts.append({"provider": provider, "query": actual_query[:300], "status": status,
                                     "accepted": len(self._rank(query, results, preferred_domains)),
                                     "latency_ms": round((time.monotonic() - t) * 1000)})
                    preferred_found = any(preferred_host(r.url, preferred_domains) for r in ranked)
                    conflict = _conflicting_date_claims(ranked)
                    if ranked and (not preferred_domains or preferred_found):
                        if attempt_index == 0 and conflict and len(providers) == 3:
                            # Go straight to the one refinement when relevant
                            # results disagree. Repeating the broad query loses
                            # time that is needed for reading the two sources.
                            providers[1], providers[2] = providers[2], providers[1]
                        elif not conflict or (attempt_index > 0 and self._rank(query, results, preferred_domains)):
                            break
                needs_pages = bool(re.search(r"релиз|выход|выйдет|верси|release|version|\bкогда\b|\bdate\b", query, re.I))
                date_claims = {m.group(0) for r in ranked for m in re.finditer(r"\b20\d{2}\b", r.snippet)}
                if ranked and (needs_pages or len(date_claims) > 1):
                    reads = await asyncio.gather(*(self._page(r, query) for r in ranked[:2]))
                    ranked = self._rank(query, [*reads, *ranked[2:]], preferred_domains)
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        status = "ok" if ranked else (attempts[-1]["status"] if attempts else "timeout")
        if status in {"ok", "cooldown"} and not ranked:
            status = "empty" if status == "ok" else "blocked"
        providers_used = "+".join(dict.fromkeys(r.provider for r in ranked)) or "+".join(dict.fromkeys(a["provider"] for a in attempts))
        return self._snapshot(query, results=ranked, status=status, provider=providers_used or "duckduckgo",
                              attempts=tuple(attempts), latency_ms=round((time.monotonic() - start) * 1000))

    @staticmethod
    def _snapshot(query, *, results=None, answer=None, status, **kwargs):
        return SearchSnapshot(query=query, results=tuple((results or [])[:3]), answer=answer,
                              status=status, searched_at=datetime.now(UTC).isoformat(), **kwargs)

    def _parse_ddg_html(self, html_text, max_items=3):
        parser = _DuckDuckGoHTMLParser()
        parser.feed(html_text)
        return [*parser.results, *(SearchResult(t, "", u) for t, u in parser._pending)][:max_items]
