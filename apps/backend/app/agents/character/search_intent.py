"""Conservative search planning for explicit requests, without a model roundtrip."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable

from apps.backend.app.environment.retrieval import internet_forbidden, normalize_entity, sensitive_query, terms


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    fallback_query: str | None = None
    preferred_domains: tuple[str, ...] = ()
    force_refresh: bool = False
    mode: str = "web"
    since: str = ""
    until: str = ""


_COMMAND = re.compile(r"\b(?:найди|поищи|поискать|погугли|загугли|погуглить|гугли|ищи|(?:посмотри|глянь|проверь)\s+в\s+(?:интернете|инете|сети)|search\s+(?:for|the\s+web)|look\s+up)\b", re.I)
_FRESH = re.compile(r"\b(?:когда\s+(?:выйдет|выходит|выход|релиз)|дата\s+(?:выхода|релиза)|когда.{0,80}\bрелиз|(?:актуальн\w*|последн\w*|новейш\w*|текущ\w*)\s+верси\w*|какая.{0,40}\bверсия|сколько\s+сейчас\s+стоит|when.{0,80}\b(?:release|launch)|latest\s+version)\b", re.I)
_LOCAL = re.compile(r"\b(?:в\s+(?:этом|моем|данном)\s+(?:коде|тексте|файле)|перепиши|отредактируй|переведи|исправь\s+(?:код|текст)|(?:как|почему|зачем)\s+(?:работает|работал|устроен)|(?:как|почему)\s+найти|(?:ошибк\w*|опечатк\w*)\s+в\s+(?:код\w*|текст\w*)|(?:ты|она)\s+(?:умеешь|умеет|может)\s+(?:искать|найти)|я\s+(?:сам\s+)?(?:найду|поищу|погуглю)|(?:не|не\s+надо|не\s+нужно)\s+(?:найди|поищи|погугли))\b", re.I)
_FOLLOWUP = re.compile(r"\b(?:ты.{0,35}\bнайди|найди\s+не\s+я|(?:ну\s+)?(?:и\s+)?что\s+там|что\s+с\s+поиском|ты.{0,60}\b(?:ищешь|искать)|але|алло|ты\s+тут|(?:найди|поищи|проверь)\s+(?:это|еще\s+раз|заново|лучше)|ищи\s+(?:ты|сама)|поищи\s+(?:ты|сама))\b", re.I)
_FILLER = re.compile(r"\b(?:пожалуйста|плиз|ирис|iris|ты|сама|сам|мне|нам|это|то|не|я|нет|ну|так|с|в|и|там|данные|информацию|информация|что|же|еще|раз|заново|лучше|нормально|давай|теперь|уже|бля|блять|смысле|ебаный|свет|поиск|поиском)\b", re.I)
_RECENT = re.compile(r"\b(?:последн\w*|нов\w*|свеж\w*)\s+(?:перс\w*|геро\w*|обновлен\w*|патч\w*)|\b(?:latest|newest)\s+(?:hero|character|update)\b", re.I)
_DETAIL = re.compile(r"^\s*(?:(?:вот|прям|еще|ну|это|не|нет|да|а)\s+)*(?:сейчас|в\s+этом\s+году|вчера|сегодня|недавно|другой\s+(?:вариант|анекдот)|за\s+(?:неделю|месяц))\b", re.I)
_RETRY = re.compile(r"\b(?:заново|еще\s+раз|по\s+другому|лучше|другой)\b", re.I)
_ENTITY = re.compile(r"\b(?:deadlock|gta\s+(?:[456]|iv|v|vi)|python|valorant|minecraft|r\.?e\.?p\.?o\.?)\b", re.I)
_EVENT = re.compile(r"выбор\w*|госдум\w*|государственн\w*\s+дум\w*|чемпионат\w*|кубок\w*|world\s*cup|election", re.I)
_OUTCOME = re.compile(r"\b(?:кто\s+(?:выиграл|победил|победитель)|результат\w*|итоги)\b", re.I)


def _event_request(text: str) -> SearchRequest | None:
    if not _EVENT.search(text) or not (_OUTCOME.search(text) or re.search(r"20\d{2}|двадцать|сейчас|последн", text)):
        return None
    year = re.search(r"\b20\d{2}\b", text)
    spoken_year = re.search(r"двадцать\s+(четверт\w*|пят\w*|шест\w*|седьм\w*)", text)
    if year:
        year = year[0]
    elif spoken_year:
        endings = {"четверт": 4, "пят": 5, "шест": 6, "седьм": 7}
        year = str(2020 + next(n for stem, n in endings.items() if spoken_year[1].startswith(stem)))
    else:
        year = ""
    if re.search(r"госдум|государственн\w*\s+дум", text):
        year = year or str(datetime.now().astimezone().year)
        return SearchRequest(f"выборы Государственная Дума России {year} итоги результаты",
                             f"ЦИК общие результаты выборов Государственная Дума {year}", ("cikrf.ru", "consultant.ru"))
    if re.search(r"(?:чемпионат\w*\s+мира|worldcup).{0,20}(?:футбол|football)", text):
        period = year or "последний"
        return SearchRequest(f"чемпионат мира по футболу {period} победитель финал",
                             f"FIFA World Cup {year or 'latest'} final winner", ("fifa.com",))
    query = " ".join(_FILLER.sub(" ", text).split())[:300]
    return SearchRequest(query) if len(terms(query)) >= 2 else None


def search_requested(text: str) -> bool:
    return not (internet_forbidden(text) or sensitive_query(text) or _LOCAL.search(text)) and bool(
        _COMMAND.search(text) or _FRESH.search(text) or _RECENT.search(text) or _FOLLOWUP.search(text) or _DETAIL.search(text) or (_EVENT.search(text) and _OUTCOME.search(text)))


def needs_query_planner(text: str, recent_messages: Iterable = ()) -> bool:
    """An explicit but unresolved request must not become an invented query."""
    users = [m for m in recent_messages if getattr(m, "role", None) == "user"][-8:]
    explicit = bool(_COMMAND.search(text) or _FRESH.search(text) or _RECENT.search(text) or (_EVENT.search(text) and _OUTCOME.search(text)))
    contextual = bool(users and (_DETAIL.search(text) or _FOLLOWUP.search(text)) and
                      any(_COMMAND.search(m.content) or _FRESH.search(m.content) or _RECENT.search(m.content) or _event_request(m.content) for m in users))
    return search_requested(text) and (explicit or contextual) and plan_search(text, users) is None


def _meaningful(query: str) -> bool:
    return bool(_ENTITY.search(query) or len(terms(query)) >= 2)


def _fact(text: str) -> str:
    if _RECENT.search(text):
        return "последний новый герой" if re.search(r"перс|геро|hero|character", text, re.I) else "последнее обновление"
    return " ".join(_FILLER.sub(" ", text).split())


def _continue(request: SearchRequest, detail: str, user_text: str) -> SearchRequest:
    query = request.query
    if re.search(r"\b(?:сейчас|в этом году)\b", detail + " " + user_text, re.I) and _EVENT.search(query):
        year = str(datetime.now().astimezone().year)
        query = re.sub(r"\b20\d{2}\b", year, query)
        fallback = re.sub(r"\b20\d{2}\b", year, request.fallback_query) if request.fallback_query else None
        return replace(request, query=query, fallback_query=fallback, force_refresh=bool(_RETRY.search(user_text)))
    if _DETAIL.search(user_text) and re.search(r"\b(?:вчера|сегодня)\b", user_text, re.I):
        query = re.sub(r"\b(?:вчера|сегодня|недавно)\b", "", query, flags=re.I)
        detail = re.sub(r"\b(?:вчера|сегодня|недавно)\b", "", detail, flags=re.I) + " " + user_text
    return replace(request, query=" ".join((query + " " + detail).split())[:300],
                   force_refresh=bool(_RETRY.search(user_text)))


def _request(text: str) -> SearchRequest | None:
    if internet_forbidden(text) or sensitive_query(text) or _LOCAL.search(text):
        return None
    event = _event_request(normalize_entity(text))
    if event:
        return event
    command = _COMMAND.search(text)
    if not command and not (_FRESH.search(text) or _RECENT.search(text)):
        return None
    query = text[command.end():] if command else text
    # STT may spell a product's number as a word; preserve the exact version.
    query = normalize_entity(query)
    gta = re.search(r"\bgta\s+([456])\b", query)
    if gta:
        number = {"4": "IV", "5": "V", "6": "VI"}[gta[1]]
        fact = "дата выхода" if re.search(r"релиз|выход|выйдет|release|launch", text, re.I) else _FILLER.sub(" ", query[gta.end():]).strip(" ,.!?:")
        if "дата выхода" == fact:
            if re.search(r"\b(?:пк|pc|компьютер\w*)\b", query):
                fact += " на ПК"
            elif re.search(r"\b(?:ps5|playstation\s*5)\b", query):
                fact += " на PS5"
            elif "xbox" in query:
                fact += " на Xbox"
        if not fact:
            fact = "официальная информация"
        return SearchRequest(f"GTA {number} {fact}"[:300],
                             f"Grand Theft Auto {number} {fact} latest announcement site:rockstargames.com", ("rockstargames.com",))
    query = re.sub(r"^\s*(?:о|об|про|about)\s+", "", query, flags=re.I)
    query = " ".join(_FILLER.sub(" ", query).split()).strip(" ,.!?:")[:300]
    query = re.sub(r"\b(?:в\s+)?(?:инете|интернете|можешь|прям|должно\s+быть)\b", " ", query, flags=re.I)
    query = " ".join(query.split()).strip(" ,.!?:")
    entity = _ENTITY.search(query)
    if entity and _RECENT.search(query):
        period = " ".join(re.findall(r"\b(?:вчера|сегодня|недавно)\b", query))
        query = f"{entity[0]} {_fact(query)} {period}".strip()
    if not entity and re.search(r"(?:че|что)[ -]нибудь|вернемся к этому вопросу|\bдопустим\b", query, re.I):
        return None
    if not _meaningful(query) or (not command and not _ENTITY.search(query)):
        return None
    return SearchRequest(query, force_refresh=bool(_RETRY.search(text)))


def plan_search(user_text: str, recent_messages: Iterable = ()) -> SearchRequest | None:
    """Use the current request, or a recent user topic for an explicit correction.

    Never turn assistant prose, memory, or an entire transcript into a query.
    Generic greetings and search troubleshooting do not activate retrieval.
    """
    if internet_forbidden(user_text) or sensitive_query(user_text) or _LOCAL.search(user_text):
        return None
    user_text = user_text.replace("ё", "е")
    request = _request(user_text)
    users = [m for m in recent_messages if getattr(m, "role", None) == "user"][-8:]
    # A request for a different anecdote needs the quoted fragment, not just
    # the generic word 'анекдот'. Other self-contained requests stand alone.
    contextual = bool(_RETRY.search(user_text) and re.search(r"анекдот|вариант", user_text, re.I))
    if request is not None and not contextual:
        return request
    if len(user_text) > 300 or not search_requested(user_text):
        return None
    fragments = []
    for message in reversed(users):
        text = normalize_entity(message.content)
        if text.strip() == user_text.strip():
            continue
        if internet_forbidden(text) or sensitive_query(text):
            return None
        if contextual and re.search(r"анекдот", user_text, re.I) and not re.search(r"анекдот|доктор|памят", text):
            # A new subject cannot inherit a previous game's lookup.
            if _ENTITY.search(text):
                return None
            continue
        request = _request(text)
        if request is not None:
            detail = " ".join(reversed(fragments))
            if _DETAIL.search(user_text):
                detail += " " + user_text
            return _continue(request, detail, user_text)
        if contextual and re.search(r"доктор|анекдот|памят", text):
            query = "анекдот " + " ".join(reversed([*fragments, text]))
            return SearchRequest(query[:300], force_refresh=True)
        entity = _ENTITY.search(text)
        if entity and fragments:
            detail = " ".join(reversed(fragments))
            if _DETAIL.search(user_text):
                detail += " " + user_text
            return _continue(SearchRequest(entity[0]), detail, user_text)
        if _RECENT.search(text) or _DETAIL.search(text):
            if _RECENT.search(text):
                fragments.append(_fact(text))
            elif re.search(r"вчера|сегодня|недел|месяц|сейчас|этом году", text):
                fragments.append("сейчас" if re.search(r"сейчас|этом году", text) else text)
            continue
        if _FOLLOWUP.search(text):
            continue
        if not search_requested(text):
            break
    return None
