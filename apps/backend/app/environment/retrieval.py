"""Small deterministic helpers shared by search and RSS retrieval (no LLM calls)."""
from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_URL = re.compile(r"https?://\S+", re.I)
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = set("что как когда где какой какая какие сейчас сегодня последние свежие новости новостей новое нового главные события мире про для за это она они мне расскажи покажи найди искать поиск интернет интернете вышел выйдет выход выхода дата релиз релиза версия версии актуальная актуальные официальный официально сайт the a an of to in on is are when what latest current release date official news stable version please all how set setup configure microphone documentation docs".split())
_ALIASES = {"гта": "gta", "ии": "ai", "россия": "russia", "россии": "russia", "росси": "russia", "игр": "gaming", "игры": "gaming", "техно": "technology", "наука": "science", "науки": "science"}
_STOP.discard("microphone")
_STOP.update("кто последний самое самый победитель выиграл победил финал итоги результаты winner final won".split())
_MODIFIERS = set("hero heroes character characters new newest update updates patch notes full text alternative another joke doctor memory announcement announced launch launched available recent recently yesterday october september january february march april may june july august november december".split())


def internet_forbidden(text: str) -> bool:
    return bool(re.search(r"\b(?:не\s+(?:ищи|гугли|используй\s+интернет|обращайся\s+(?:к\s+интернету|ни\s+к\s+чему))|без\s+(?:веб[ -]?поиска|поиска\s+в\s+интернете|интернета)|(?:ни\s+поиску|по\s+знаниям\s+модели)|do\s+not\s+(?:search|browse)|don['’]t\s+(?:search|browse))\b", text, re.I))


def sensitive_query(text: str) -> bool:
    """Reject obvious private identifiers before either search provider sees them."""
    return bool(re.search(
        r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|\bsk-[a-zA-Z0-9_-]{12,}|"
        r"\b(?:api[_ -]?key|password|пароль|токен)\s*[:=]\s*\S+|"
        r"(?<!\w)(?:\+?\d[ ()-]*){10,15}(?!\w)|[a-zA-Z]:\\",
        text, re.I,
    ))


def clean_text(value: str, max_chars: int = 2000) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()[:max_chars]


def model_text(value: str, max_chars: int = 2000) -> str:
    """Links are durable metadata, never model evidence or spoken text."""
    return clean_text(_URL.sub("", value), max_chars)


def canonical_url(value: str) -> str:
    try:
        p = urlsplit(html.unescape(value))
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
            return ""
        query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in {"gsid", "ysclid", "fbclid", "gclid"}]
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", urlencode(query), ""))
    except ValueError:
        return ""


def normalize_entity(value: str) -> str:
    text = value.casefold().replace("ё", "е")
    # Spelling equivalence for matching, not a factual assertion of identity.
    text = re.sub(r"\b(?:gone[. -]?fludd|гон[ -]?(?:флат|флад|флудд?))\b", "gonefludd", text)
    text = re.sub(r"\bлсп\b", "lsp", text)
    text = re.sub(r"\b(?:дедлок|дэдлок|дыдлок|дед\s+лок)(?:а|е|у|ом)?\b", "deadlock", text)
    text = re.sub(r"\b(?:питон|пайтон)\b", "python", text)
    text = re.sub(r"\b(?:госдум\w*|государственн\w*\s+дум\w*)\b", "госдума", text)
    text = re.sub(r"\b(?:чемпионат\w*\s+мира|world\s+cup|чм)\b", "worldcup", text)
    text = re.sub(r"\b(?:искусственн\w*\s+интеллект\w*|artificial\s+intelligence)\b", "ai", text)
    text = re.sub(r"\b(?:grand\s+theft\s+auto|гта|джи\s+ти\s+эй)\b", "gta", text)
    text = re.sub(r"\bgta\s+(шесть|шестая|six|пять|пятая|five|четыре|four)\b",
                  lambda m: "gta " + {"шесть": "6", "шестая": "6", "six": "6", "пять": "5", "пятая": "5", "five": "5", "четыре": "4", "four": "4"}[m[1]], text)
    text = re.sub(r"\bgta\s*(vi|v|iv|6|5|4)\b", lambda m: "gta " + {"vi": "6", "v": "5", "iv": "4"}.get(m[1], m[1]), text)
    return text


def terms(value: str) -> set[str]:
    words = _WORDS.findall(normalize_entity(value))
    out = set()
    for word in words:
        if word.startswith(("геро", "персон", "перс")):
            word = "hero"
        if word.startswith("футбол") or word in {"fifa", "soccer"}:
            word = "football"
        elif word.startswith("хокке"):
            word = "hockey"
        if word.startswith("микрофон"):
            word = "microphone"
        elif word.startswith("нейросет"):
            word = "ai"
        if word in _STOP or (len(word) < 2 and not word.isdigit()):
            continue
        stem = word[:5] if re.search(r"[а-я]", word) and len(word) > 5 else word
        out.add(_ALIASES.get(word, _ALIASES.get(stem, stem)))
    return out


def relevance(query: str, text: str) -> float:
    query = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", query)
    q, candidate = terms(query), terms(text)
    if not q:
        return 0.0
    if re.search(r"(?:по)?удал|убрал|исчез|removed|deleted", query, re.I) and not re.search(r"(?:по)?удал|убрал|исчез|заблок|недоступ|removed|deleted|unavailable", text, re.I):
        return 0.0
    if re.search(r"(?:по)?удал|removed|deleted", query, re.I) and not re.search(r"вернул|возврат|returned", query, re.I) and re.search(r"вернул|возврат|returned", text[:180], re.I):
        return 0.0
    for entity in ("gonefludd", "lsp"):
        if entity in q and entity not in candidate:
            return 0.0
    # Named Latin products and their versions must not disappear in a vaguely
    # related article; in particular GTA V must never corroborate GTA VI.
    latin = [w for w in _WORDS.findall(normalize_entity(query))
             if w in q and re.fullmatch(r"[a-z]+\d*", w) and w not in _MODIFIERS]
    event_year = bool(re.search(r"выбор|чемпионат|кубок|world\s+cup|election", query, re.I))
    anchors = set(latin[:1]) | {w for w in q if w.isdigit() and (event_year or not re.fullmatch(r"20\d{2}", w))}
    if "microphone" in q:
        anchors.add("microphone")
    if "worldcup" in q:
        anchors.update(q & {"football", "hockey", "basketball"})
    if anchors and not anchors.issubset(candidate):
        return 0.0
    overlap = len(q & candidate) / len(q)
    return overlap if overlap >= 0.34 else 0.0


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def preferred_host(url: str, domains: tuple[str, ...]) -> bool:
    host = urlsplit(url).hostname or ""
    return any(host == d or host.endswith("." + d) for d in domains)
