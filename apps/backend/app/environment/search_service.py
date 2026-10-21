"""Bounded, key-free web search used by Iris during a conversation turn."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field, replace
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
import sqlite3
from pathlib import Path
from contextvars import ContextVar
import xml.etree.ElementTree as ET

import httpx

from apps.backend.app.environment.retrieval import canonical_url, clean_text, model_text, parse_date, preferred_host, relevance, sensitive_query, terms
from apps.backend.app.environment.search_providers import API_PROVIDERS, api_search
from apps.backend.app.environment.search_budget import SearchBudget

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_MAX_QUERY_CHARS = 300
_MAX_TITLE_CHARS = 120
_MAX_SNIPPET_CHARS = 300
_API_SENT = ContextVar("search_api_sent", default=False)


@dataclass
class SearchTurnBudget:
    deadline: float
    queries: set[str] = field(default_factory=set)
    requests: int = 0
    pages: int = 0
    page_results: dict[str, SearchResult] = field(default_factory=dict)
    denied_api: dict[str, str] = field(default_factory=dict)

    def admit(self, query: str) -> bool:
        normalized = clean_text(query, 300).casefold()
        if time.monotonic() >= self.deadline or self.requests >= 6 or (normalized not in self.queries and len(self.queries) >= 3):
            return False
        self.queries.add(normalized)
        self.requests += 1
        return True


def _outcome_query(query: str) -> bool:
    return bool(re.search(r"выбор|чемпионат|world\s+cup|election", query, re.I) and
                re.search(r"результат|итог|побед|выиграл|winner|final", query, re.I))


def _outcome_evidence(result: SearchResult) -> bool:
    evidence = result.page_text or result.snippet
    if re.search(r"прогноз|предсказ|симуляци|победит\b|как может|может измениться|prediction|simulation", result.title + " " + evidence, re.I):
        return False
    return bool(re.search(r"победил|победила|выиграл|выиграла|чемпион\w*.{0,15}стал|\d+\s*(?:мандат|мест)|набрал|набрала|\d+(?:[.,]\d+)?\s*%|\bwon\b|winner|defeated|beat\b", evidence, re.I))


def _final_outcome_evidence(result: SearchResult) -> bool:
    text = result.title + " " + (result.page_text or result.snippet)
    if not _outcome_evidence(result) or re.search(r"предварительн|неполны|экзитпол|preliminary|exit[ -]poll|early results", text, re.I):
        return False
    if re.search(r"выбор|госдум|государственн\w*\s+дум|election", text, re.I):
        return bool(re.search(r"окончательн|утвердил|утвержден|общие результаты|100\s*%|official final|certified results", text, re.I))
    return True


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
    content_truncated: bool = False


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
    mode: str = "web"
    since: str = ""
    until: str = ""
    evidence_status: str = ""
    quota: dict | None = None
    requested_fact: str = ""

    def compact_summary(self, max_items: int = 3, max_chars: int = 1600) -> str:
        """Return bounded facts for the model; URLs stay in durable metadata."""
        lines = [f"Результаты поиска по запросу «{model_text(self.query, 300)}»:"]
        if _outcome_query(self.query):
            lines.append("Нужен итог события: расписание, подготовка и прогнозы не подтверждают победителя. Проверяй год события; не дополняй цифры и имена из догадок.")
            if not any(_outcome_evidence(r) for r in self.results):
                lines.append("Найдена только информация по теме; подтверждённого итога в полученном содержании нет.")
            elif not any(_final_outcome_evidence(r) for r in self.results):
                lines.append("Получены предварительные итоги; не называй их окончательными.")
        if self.answer:
            lines.append(f"Краткий ответ: {self.answer[:_MAX_SNIPPET_CHARS]}")
        selected = list(self.results[:max_items])
        # Spend most of the existing context budget on the best read document.
        best_read = next((i for i, r in enumerate(selected) if r.page_status == "read"), None)
        for index, res in enumerate(selected, 1):
            date = f" ({res.published_at[:10]})" if res.published_at else ""
            evidence = res.page_text or res.snippet
            limit = max(600, max_chars - 800 - 450 * (len(selected) - 1)) if index - 1 == best_read else 300
            limitation = " [только поисковый сниппет]" if res.page_status != "read" else ""
            if res.content_truncated or len(evidence) > limit:
                limitation += " [содержание сокращено; полнота не подтверждена]"
            if not res.published_at and re.search(r"новост|\bnews\b", self.query, re.I):
                limitation += " [дата публикации неизвестна]"
            document = _evidence_excerpt(evidence, self.requested_fact or self.query, limit) if res.page_status == "read" else model_text(evidence, limit)
            lines.append(f"[S{index}] {model_text(res.title, _MAX_TITLE_CHARS)}{date}: {document}{limitation}")
        lines.append("Дата публикации не равна дате события или релиза. Факты вне этих данных не подтверждены проверкой.")
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
            "topic": self.query,
            "mode": self.mode,
            "since": self.since,
            "until": self.until,
            "quota": self.quota,
            "requested_fact": self.requested_fact or ("outcome" if _outcome_query(self.query) else ""),
            "evidence_status": self.evidence_status or ("none" if not self.results else "topic_only" if _outcome_query(self.query) and not any(_outcome_evidence(r) for r in self.results)
                                else "provisional" if _outcome_query(self.query) and not any(_final_outcome_evidence(r) for r in self.results) else "available"),
            "sources": [
                {"id": f"S{index}", "title": item.title, "url": item.url, "published_at": item.published_at,
                 "page_status": item.page_status, "provider": item.provider, "modified_at": item.modified_at,
                 "evidence": _evidence_excerpt(item.page_text or item.snippet, self.requested_fact or self.query, 1800 if index == 1 else 400),
                 "content_truncated": item.content_truncated or len(item.page_text or item.snippet) > (1800 if index == 1 else 400)}
                for index, item in enumerate(self.results, 1)
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



def _document_text(value: str, max_chars: int = 4000) -> str:
    """Keep document order/line breaks, while removing URLs from spoken evidence."""
    value = re.sub(r"https?://\S+", "", html.unescape(value))
    return "\n".join(re.sub(r"[ \t\r]+", " ", line).strip() for line in value.splitlines()).strip()[:max_chars]


def _evidence_excerpt(value: str, query: str, max_chars: int) -> str:
    """Use the bounded window for the requested fragment, keeping its order."""
    document = _document_text(value, 16000)
    if len(document) <= max_chars:
        return document
    lines = document.splitlines(keepends=True)
    wanted = terms(query)
    scores = [len(wanted & terms(line)) for line in lines]
    best = max(range(len(lines)), key=lambda i: scores[i], default=0)
    offset = sum(len(line) for line in lines[:best])
    start = max(0, offset - min(150, max_chars // 5))
    if start:
        boundary = document.find("\n", start, offset)
        start = boundary + 1 if boundary >= 0 else start
    return document[start:start + max_chars].strip()


class _ArticleParser(HTMLParser):
    """Collect paragraphs and publication metadata without executing page code."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.paragraphs, self.current, self.dates, self.ld = [], [], [], [], []
        self.capture, self.description, self.ld_capture = None, "", False
        self.capture_depth = 0
        self.content_truncated = False
        self.used_description = False
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
        if self.capture:
            if tag == self.capture:
                self.capture_depth += 1
            if tag in {"br", "p", "div", "h1", "h2", "h3"}:
                self.current.append("\n")
        elif tag in {"p", "h1", "h2", "h3", "div", "pre"}:
            self.capture, self.current = tag, []
            self.capture_depth = 1

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
            self.capture_depth -= 1
            if self.capture_depth:
                self.current.append("\n")
                return
            raw = "".join(self.current)
            text = _document_text(raw, 16000)
            self.content_truncated |= len(raw) > 4000
            if len(text) >= 20:
                self.paragraphs.append(text)
            self.capture, self.current = None, []
        elif self.capture and tag in {"p", "div", "h1", "h2", "h3"}:
            self.current.append("\n")

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
                        self.paragraphs.append(_document_text(body, 16000))
                        self.content_truncated |= len(body) > 4000
                    queue.extend(v for v in item.values() if isinstance(v, (dict, list)))
        paragraphs = self.paragraphs or ([self.description] if self.description else [])
        self.used_description = not bool(self.paragraphs)
        ranked = sorted(enumerate(paragraphs), key=lambda x: (-relevance(query, x[1]), x[0]))
        selected = sorted(ranked[:4])
        document = "\n".join(p for _, p in selected)
        self.content_truncated |= len(document) > 4000 or len(paragraphs) > 4
        text = _evidence_excerpt(document, query, 4000)
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
    def __init__(self, http_client: httpx.AsyncClient | None = None, *, runtime_settings=None, credentials=None, budget_path: Path | None = None) -> None:
        self._client = http_client
        self._page_client = http_client
        self._cache_lock = asyncio.Lock()
        self._cache = OrderedDict()
        self._inflight, self._inflight_waiters, self._blocked_until = {}, {}, {}
        self._cache_ttl_seconds, self._error_ttl_seconds = 300, 30
        self._cache_max_entries, self._deadline_seconds = 256, 15.0
        self._runtime_settings = runtime_settings
        self._credentials = dict(credentials or {})
        self._budget = SearchBudget(budget_path)
        self._quota = None
        self._admission_lock = asyncio.Lock()
        self._eligibility_denials = {}

    def selected_provider(self) -> str:
        provider = getattr(self._runtime_settings, "web_search_provider", "free")
        return provider if provider == "tavily" else "free"

    def configured_providers(self) -> dict[str, bool]:
        return {name: bool(self._credentials.get(name)) for name in API_PROVIDERS}

    async def check_provider(self, provider: str) -> dict[str, object]:
        if provider not in API_PROVIDERS:
            return {"provider": provider, "status": "invalid"}
        results, status = await self._api_provider(provider, "Python documentation")
        return {"provider": provider, "status": status, "results_count": len(results), "quota": self._quota if provider == "tavily" else None}

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
                     preferred_domains: tuple[str, ...] = (), force_refresh: bool = False,
                     mode: str = "web", since: str = "", until: str = "",
                     deadline: float | None = None, budget: SearchTurnBudget | None = None, progress=None) -> SearchSnapshot:
        clean_q = clean_text(query, 300)
        fallback = clean_text(fallback_query or "", 300)
        domains = tuple(sorted({d.lower().strip().removeprefix("www.") for d in preferred_domains
            if isinstance(d, str) and re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", d.strip())}))[:3]
        if not clean_q:
            return self._snapshot("", status="empty")
        if sensitive_query(clean_q) or sensitive_query(fallback):
            return self._snapshot(clean_q, status="invalid")
        key = (clean_q.casefold(), fallback.casefold(), domains, self.selected_provider(), mode, since, until)
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry and not force_refresh:
                snap, timestamp = entry
                ttl = self._cache_ttl_seconds if snap.status == "ok" else self._error_ttl_seconds
                if time.monotonic() - timestamp < ttl:
                    self._cache.move_to_end(key)
                    return replace(snap, cached=True, latency_ms=0)
                self._cache.pop(key, None)
            task = self._inflight.get(key)
            if task is None:
                async def run():
                    options = {"mode": mode, "since": since, "until": until} if mode != "web" or since or until else {}
                    if deadline is not None:
                        options["deadline"] = deadline
                    if budget is not None:
                        options["budget"] = budget
                    if progress is not None:
                        options["progress"] = progress
                    snap = await (self._perform_search(clean_q, fallback, domains, **options)
                                  if fallback or domains or options else self._perform_search(clean_q))
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
            async with asyncio.timeout(2.5):
                if provider == "duckduckgo":
                    response = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
                elif provider == "google_news":
                    response = await client.get("https://news.google.com/rss/search",
                        params={"q": query, "hl": "ru", "gl": "RU", "ceid": "RU:ru"})
                elif provider == "wikipedia":
                    subject = re.sub(r"биограф\w*|подроб\w*|исполнител\w*", "", query, flags=re.I).strip()
                    response = await client.get("https://ru.wikipedia.org/w/api.php", params={
                        "action": "query", "generator": "search", "gsrsearch": subject,
                        "gsrnamespace": 0, "gsrlimit": 3, "prop": "extracts|info", "exintro": 1,
                        "explaintext": 1, "inprop": "url", "format": "json"})
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
            elif provider == "wikipedia":
                payload = response.json()
                pages = payload.get("query", {}).get("pages", {})
                results = [SearchResult(clean_text(p.get("title", ""), 120), clean_text(p.get("extract", ""), 300),
                            canonical_url(p.get("fullurl", "")), page_text=clean_text(p.get("extract", ""), 1800),
                            page_status="snippet" if p.get("extract") else "not_read", provider=provider, content_truncated=bool(p.get("extract")))
                           for p in pages.values() if isinstance(p, dict)]
            else:
                root = ET.fromstring(response.content)
                results = [SearchResult(clean_text(i.findtext("title") or "", 120),
                    clean_text(re.sub(r"<[^>]+>", " ", html.unescape(i.findtext("description") or "")), 300), canonical_url(i.findtext("link") or ""),
                    published_at=(parse_date(i.findtext("pubDate") or "").isoformat() if parse_date(i.findtext("pubDate") or "") else ""),
                    provider=provider) for i in root.findall(".//item")[:10]]
            results = [replace(r, url=canonical_url(r.url)) for r in results if canonical_url(r.url)]
            return results, "ok" if results else "empty"
        except (TimeoutError, httpx.TimeoutException):
            return [], "timeout"
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, ET.ParseError) as exc:
            logger.debug("Search provider %s failed: %s", provider, type(exc).__name__)
            return [], "error"

    async def _api_provider(self, provider, query, *, mode="web", since="", until=""):
        _API_SENT.set(False)
        if provider != "tavily":
            return [], "free_only"
        denied = self._eligibility_denials.get(provider)
        if denied and denied[1] > time.monotonic():
            return [], denied[0]
        key = self._credentials.get(provider)
        if not key:
            return [], "unconfigured"
        if self._blocked_until.get(provider, 0) > time.monotonic():
            return [], "cooldown"
        try:
            async with self._admission_lock:
                denied = self._eligibility_denials.get(provider)
                if denied and denied[1] > time.monotonic():
                    return [], denied[0]
                async with asyncio.timeout(2.5):
                    response = await (await self._get_client()).get("https://api.tavily.com/usage", headers={"Authorization": f"Bearer {key}"})
                    response.raise_for_status()
                    if len(response.content) > 64_000:
                        self._eligibility_denials[provider] = ("unverified_free_plan", time.monotonic() + 60)
                        return [], "unverified_free_plan"
                    self._quota = await asyncio.to_thread(self._budget.reserve, response.json())
                if self._quota["status"] != "reserved":
                    self._eligibility_denials[provider] = (self._quota["status"], time.monotonic() + 60)
                    return [], self._quota["status"]
            async with asyncio.timeout(2.5):
                _API_SENT.set(True)
                rows = await api_search(await self._get_client(), provider, key, query, mode=mode, since=since, until=until)
            return [SearchResult(**row) for row in rows], "ok" if rows else "empty"
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403, 429, 432, 433}:
                self._blocked_until[provider] = time.monotonic() + 60
            return [], "unauthorized" if status == 401 else "blocked" if status in {403, 429, 432, 433} else "error"
        except (TimeoutError, httpx.TimeoutException):
            return [], "timeout"
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, OSError, sqlite3.Error):
            return [], "error"

    def _rank(self, query, results, domains, max_items=3):
        scored, seen = [], set()
        for item in results:
            score = relevance(query, item.title + " " + (item.page_text or item.snippet) + " " + (urllib.parse.urlsplit(item.url).hostname or ""))
            if not score or not item.url or item.url in seen:
                continue
            seen.add(item.url)
            score += 1.0 if preferred_host(item.url, domains) else 0
            if _outcome_query(query) and _outcome_evidence(item):
                score += 1.0
                if _final_outcome_evidence(item):
                    score += 0.5
            scored.append((score, item))
        scored.sort(key=lambda x: (-x[0], -(parse_date(x[1].published_at).timestamp() if parse_date(x[1].published_at) else 0)))
        return [r for _, r in scored[:max_items]]

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
            return replace(result, page_text=text, published_at=date or result.published_at,
                           modified_at=max(modified).isoformat() if modified else "",
                           content_truncated=parser.content_truncated,
                           page_status=("snippet" if parser.used_description else "read") if text else "unavailable")
        except (TimeoutError, httpx.HTTPError, ValueError, OSError):
            return replace(result, page_status="unavailable")

    async def read_sources(self, query, sources, *, budget, progress=None):
        """Read an already selected article with the same page/network bounds."""
        started = time.monotonic()
        selected = [r for r in sources if canonical_url(r.url) and not sensitive_query(r.url)][:2]
        results, attempts = [], []
        for source in selected:
            if source.url in budget.page_results:
                results.append(budget.page_results[source.url])
                continue
            if budget.pages >= 3 or budget.requests >= 6 or time.monotonic() >= budget.deadline:
                break
            budget.pages += 1
            budget.requests += 1
            if progress:
                progress("reading")
            try:
                async with asyncio.timeout(max(.01, budget.deadline - time.monotonic())):
                    result = await self._page(source, query)
            except TimeoutError:
                result = replace(source, page_status="unavailable")
            budget.page_results[source.url] = result
            results.append(result)
            attempts.append({"provider": "source_page", "query": query, "status": result.page_status,
                             "searched": True, "raw_count": 1, "accepted": int(result.page_status == "read")})
        return self._snapshot(query, results=results, status="ok" if results else "timeout",
                              provider="source_page", mode="news", attempts=tuple(attempts), cached=not attempts,
                              latency_ms=round((time.monotonic() - started) * 1000))

    async def _perform_search(self, query, fallback_query=None, preferred_domains=(), *, mode="web", since="", until="", deadline=None, budget=None, progress=None):
        start = time.monotonic()
        controlled = budget is not None
        budget = budget or SearchTurnBudget(deadline or start + self._deadline_seconds)
        attempts, candidates, ranked = [], [], []
        outcome = _outcome_query(query)
        topical = outcome or mode == "news" or bool(re.search(r"новост|недавн|удал|последн.{0,35}(?:геро|перс|песн|трек|релиз)|latest.{0,20}(?:hero|update|song|release)", query, re.I))
        providers = [("duckduckgo", query), ("google_news" if topical else "bing", query)]
        if re.search(r"биограф|biography", query, re.I):
            providers.insert(0, ("wikipedia", query))
        if fallback_query and fallback_query.casefold() != query.casefold():
            providers.append(("refine", fallback_query))
        elif preferred_domains:
            providers.append(("duckduckgo", query + " site:" + preferred_domains[0]))
        elif not controlled:
            refined = re.sub(r"\b(?:полный текст|full text|последний|самый|latest|recently)\b", "", query, flags=re.I)
            refined = clean_text(refined, 250)
            if refined == query:
                refined += " " + ("варианты текст" if re.search(r"анекдот|joke", query, re.I) else "подробности" if re.search(r"[а-яё]", query, re.I) else "details")
            if refined != query:
                providers.append(("refine", refined))
        refinement_query = providers[-1][1] if len(providers) >= 3 else None
        selected = self.selected_provider()
        if selected != "free":
            providers.insert(0, (selected, query))
        limit = min(6, len(providers))
        rank_limit = 7 if mode == "news" else 3
        try:
            async with asyncio.timeout(min(self._deadline_seconds, max(0, deadline - time.monotonic())) if deadline is not None else self._deadline_seconds):
                for attempt_index in range(min(limit, len(providers))):
                    provider, actual_query = providers[attempt_index]
                    if provider in budget.denied_api:
                        continue
                    if provider == "refine":
                        provider = "bing" if (topical and not outcome) or self._blocked_until.get("duckduckgo", 0) > time.monotonic() else "duckduckgo"
                    if not budget.admit(actual_query):
                        break
                    if progress:
                        progress("searching" if actual_query == query else "refining")
                    t = time.monotonic()
                    results, status = (await self._api_provider(provider, actual_query, mode=mode, since=since, until=until)
                                       if provider in API_PROVIDERS else await self._provider(provider, actual_query))
                    if provider in API_PROVIDERS and status in {"unconfigured", "unverified_free_plan", "quota_exhausted", "unauthorized", "blocked", "cooldown", "budget_unavailable", "free_only"}:
                        budget.denied_api[provider] = status
                    if since or until:
                        lower, upper = parse_date(since), parse_date(until)
                        results = [r for r in results if not parse_date(r.published_at) or
                                   ((not lower or parse_date(r.published_at) >= lower) and
                                    (not upper or parse_date(r.published_at) < upper))]
                    if attempt_index > 0 and actual_query == refinement_query and _conflicting_date_claims(ranked):
                        # On equal relevance, the focused clarification precedes
                        # the broad results that prompted the conflict.
                        candidates = [*results, *candidates]
                    else:
                        candidates.extend(results)
                    ranked = self._rank(query, candidates, preferred_domains, rank_limit)
                    attempts.append({"provider": provider, "query": actual_query[:300], "status": status,
                                     "searched": _API_SENT.get() if provider in API_PROVIDERS else status != "cooldown",
                                     "raw_count": len(results),
                                     "accepted": len(self._rank(query, results, preferred_domains)),
                                     "latency_ms": round((time.monotonic() - t) * 1000)})
                    preferred_found = any(preferred_host(r.url, preferred_domains) for r in ranked)
                    conflict = _conflicting_date_claims(ranked)
                    if ranked and (not preferred_domains or preferred_found):
                        if outcome and not any(_final_outcome_evidence(r) for r in ranked):
                            # A schedule page is related, but does not answer
                            # who won. Use the remaining bounded providers.
                            continue
                        if topical and attempt_index == 0 and not any(parse_date(r.published_at) for r in ranked):
                            # A fresh-event query needs dated evidence, not just
                            # a plausible title from the first general provider.
                            continue
                        if attempt_index == 0 and conflict and len(providers) == 3:
                            # Go straight to the one refinement when relevant
                            # results disagree. Repeating the broad query loses
                            # time that is needed for reading the two sources.
                            providers[1], providers[2] = providers[2], providers[1]
                        elif not conflict or (attempt_index > 0 and self._rank(query, results, preferred_domains)):
                            break
                needs_pages = topical or bool(re.search(r"причин|последств|объект|цел[ьиь]|диабет|инсулин|медицин|биограф|подроб|релиз|выход|выйдет|верси|release|version|\bкогда\b|\bdate\b|полны|текст|анекдот|вариант|joke|full text|геро|перс", query, re.I))
                date_claims = {m.group(0) for r in ranked for m in re.finditer(r"\b20\d{2}\b", r.snippet)}
                if ranked and (needs_pages or len(date_claims) > 1):
                    to_read = [r for r in ranked if r.page_status != "read" and r.url not in budget.page_results][:min(2, 3 - budget.pages)]
                    budget.pages += len(to_read)
                    if to_read and progress:
                        progress("reading")
                    reads = await asyncio.gather(*(self._page(r, query) for r in to_read))
                    budget.page_results.update({r.url: r for r in reads})
                    evidence = [budget.page_results.get(r.url, r) for r in ranked]
                    lower, upper = parse_date(since), parse_date(until)
                    evidence = [r for r in evidence if not parse_date(r.published_at) or
                                ((not lower or parse_date(r.published_at) >= lower) and
                                 (not upper or parse_date(r.published_at) < upper))]
                    ranked = self._rank(query, evidence, preferred_domains, rank_limit)
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        status = "ok" if ranked else (attempts[-1]["status"] if attempts else "timeout")
        if not ranked:
            statuses = {a["status"] for a in attempts}
            status = "empty" if "ok" in statuses or "empty" in statuses else "blocked" if statuses & {"blocked", "cooldown"} else "timeout" if "timeout" in statuses else status
        providers_used = "+".join(dict.fromkeys(r.provider for r in ranked)) or "+".join(dict.fromkeys(a["provider"] for a in attempts))
        return self._snapshot(query, results=ranked, status=status, provider=providers_used or "duckduckgo", quota=self._quota if selected == "tavily" else None,
                              attempts=tuple(attempts), latency_ms=round((time.monotonic() - start) * 1000), mode=mode, since=since, until=until)

    @staticmethod
    def _snapshot(query, *, results=None, answer=None, status, **kwargs):
        return SearchSnapshot(query=query, results=tuple((results or [])[:7 if kwargs.get("mode") == "news" else 3]), answer=answer,
                              status=status, searched_at=datetime.now(UTC).isoformat(), **kwargs)

    def _parse_ddg_html(self, html_text, max_items=3):
        parser = _DuckDuckGoHTMLParser()
        parser.feed(html_text)
        return [*parser.results, *(SearchResult(t, "", u) for t, u in parser._pending)][:max_items]
