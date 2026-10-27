"""Evidence gates for mutable release facts; no product answers are encoded here."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from urllib.parse import urlsplit

from apps.backend.app.environment.retrieval import normalize_entity, parse_date, preferred_host


def latest_release_question(text: str) -> bool:
    return bool(re.search(
        r"(?:последн\w*|новейш\w*|latest|newest).{0,65}(?:геро|перс|агент|релиз|выш|песн|трек|альбом|верси|hero|character|release|version|song)|"
        r"(?:геро\w*|перс\w*|агент\w*|выш\w*|релиз\w*|hero|character|release|version).{0,65}(?:последн|latest|newest)|поряд\w*.{0,25}выход", text, re.I))


def release_question(text: str) -> bool:
    return latest_release_question(text) or bool(re.search(
        r"дат\w*.{0,20}(?:выход|релиз)|когда.{0,50}(?:выш|вый|релиз)|"
        r"(?:нов\w*|new)\s+(?:геро\w*|агент\w*|перс\w*|hero|character|agent)|"
        r"\b(?:release|launch|релиз\w*)\b|when.{0,30}(?:release|launch)", text, re.I))


def release_statement(text: str) -> bool:
    return bool(re.search(
        r"выш[её]л|вышла|вышли|выпущен|добавлен|уже.{0,25}(?:игр|доступ)|теперь.{0,25}доступ|"
        r"\breleased\b|is\s+(?:out|available)|now\s+(?:joins|available)|joining\s+us\s+today|has\s+(?:launched|joined)", text, re.I))


def release_domains(text: str) -> tuple[str, ...]:
    # Only source locations, never names of heroes, dates or release order.
    text = normalize_entity(text)
    if re.search(r"\bdeadlock\b", text):
        return ("store.steampowered.com", "steamcommunity.com", "playdeadlock.com")
    if re.search(r"\bgta\b", text):
        return ("rockstargames.com",)
    if re.search(r"\bminecraft\b", text):
        return ("minecraft.net",)
    return ()


def official_release_feed(text: str) -> tuple[str, str] | None:
    """Known public source endpoints, independent of the current release."""
    if release_question(text) and re.search(r"\bdeadlock\b", normalize_entity(text)):
        return "Deadlock", "https://store.steampowered.com/feeds/news/app/1422450/?l=english"
    return None


def primary_release_source(url: str, domains) -> bool:
    parsed = urlsplit(url)
    host, path = parsed.hostname or "", parsed.path
    if not preferred_host(url, domains) or "forum" in host or re.search(r"/(?:discussions|sharedfiles|workshop)(?:/|$)", path):
        return False
    if host == "steamcommunity.com":
        return bool(re.match(r"/(?:games|ogg)/[^/]+/announcements/detail/", path))
    return True


def release_evidence_problem(results, question: str, quote: str, canonical: str = "", domains=()) -> str:
    """A model's enough=true cannot turn a schedule/snippet into a release."""
    if not release_question(question):
        return ""
    normalized_quote = " ".join(quote.split()).casefold() if isinstance(quote, str) else ""
    read = [r for r in results if r.page_status == "read" and len(normalized_quote) >= 16
            and normalized_quote in " ".join(r.page_text.split()).casefold()]
    if not read:
        return "Нет точной цитаты с искомым фактом из прочитанной страницы."
    if canonical and normalize_entity(canonical) not in normalize_entity(quote):
        return "Имя не подтверждено цитатой о релизе; список имён не устанавливает их тождество."
    if latest_release_question(question):
        if re.search(r"выйдет|ожидается|запланирован|предполож|не\s+(?:выш[её]л|вышла|выпущен)|will\s+(?:be|join|arrive|release)|not\s+(?:yet\s+)?(?:released|available)|scheduled|expected|upcoming", quote, re.I):
            return "Расписание или анонс не подтверждает состоявшийся выход и текущий порядок релизов."
        if not release_statement(quote):
            return "Цитата не подтверждает состоявшийся релиз."
        cutoff = datetime.now(UTC) - timedelta(days=7)
        if not any((date := parse_date(r.modified_at or r.published_at)) and cutoff <= date <= datetime.now(UTC) for r in read):
            return "Старый или недатированный источник не устанавливает, какой релиз последний сейчас."
    if domains and not any(primary_release_source(r.url, domains) for r in read):
        return "Релиз не сверен с прочитанным первоисточником; сторонний гайд может быть устаревшим."
    return ""
