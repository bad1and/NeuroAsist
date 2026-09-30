"""Conservative search planning for explicit requests, without a model roundtrip."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from apps.backend.app.environment.retrieval import internet_forbidden, normalize_entity, sensitive_query, terms


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    fallback_query: str | None = None
    preferred_domains: tuple[str, ...] = ()


_COMMAND = re.compile(r"\b(?:найди|поищи|погугли|загугли|гугли|ищи|посмотри\s+в\s+(?:интернете|сети)|проверь\s+в\s+(?:интернете|сети)|search\s+(?:for|the\s+web)|look\s+up)\b", re.I)
_FRESH = re.compile(r"\b(?:когда\s+(?:выйдет|выходит|выход|релиз)|дата\s+(?:выхода|релиза)|когда.{0,80}\bрелиз|(?:актуальн\w*|последн\w*|новейш\w*|текущ\w*)\s+верси\w*|какая.{0,40}\bверсия|сколько\s+сейчас\s+стоит|when.{0,80}\b(?:release|launch)|latest\s+version)\b", re.I)
_LOCAL = re.compile(r"\b(?:в\s+(?:этом|моем|данном)\s+(?:коде|тексте|файле)|перепиши|отредактируй|переведи|исправь\s+(?:код|текст)|(?:как|почему|зачем)\s+(?:работает|работал|устроен)|(?:как|почему)\s+найти|(?:ошибк\w*|опечатк\w*)\s+в\s+(?:код\w*|текст\w*)|(?:ты|она)\s+(?:умеешь|умеет|может)\s+(?:искать|найти)|я\s+(?:сам\s+)?(?:найду|поищу|погуглю)|(?:не|не\s+надо|не\s+нужно)\s+(?:найди|поищи|погугли))\b", re.I)
_FOLLOWUP = re.compile(r"\b(?:ты.{0,35}\bнайди|найди\s+не\s+я|(?:ну\s+)?(?:и\s+)?что\s+там|что\s+с\s+поиском|ты.{0,60}\b(?:ищешь|искать)|але|алло|ты\s+тут|(?:найди|поищи|проверь)\s+(?:это|еще\s+раз|заново|лучше)|ищи\s+(?:ты|сама)|поищи\s+(?:ты|сама))\b", re.I)
_FILLER = re.compile(r"\b(?:пожалуйста|плиз|ирис|iris|ты|сама|сам|мне|нам|это|то|не|я|нет|ну|так|с|в|и|там|данные|информацию|информация|что|же|еще|раз|заново|лучше|нормально|давай|теперь|уже|бля|блять|смысле|ебаный|свет|поиск|поиском)\b", re.I)


def _request(text: str) -> SearchRequest | None:
    if internet_forbidden(text) or sensitive_query(text) or _LOCAL.search(text):
        return None
    command = _COMMAND.search(text)
    if not command and not _FRESH.search(text):
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
    if not terms(query):
        return None
    return SearchRequest(query)


def plan_search(user_text: str, recent_messages: Iterable = ()) -> SearchRequest | None:
    """Use the current request, or a recent user topic for an explicit correction.

    Never turn assistant prose, memory, or an entire transcript into a query.
    Generic greetings and search troubleshooting do not activate retrieval.
    """
    if internet_forbidden(user_text) or sensitive_query(user_text) or _LOCAL.search(user_text):
        return None
    request = _request(user_text)
    if request is not None:
        return request
    if len(user_text) > 180 or not _FOLLOWUP.search(user_text):
        return None
    users = [m for m in recent_messages if getattr(m, "role", None) == "user"][-6:]
    for message in reversed(users):
        text = message.content
        if text.strip() == user_text.strip():
            continue
        if internet_forbidden(text) or sensitive_query(text):
            return None
        request = _request(text)
        if request is not None:
            return request
        if not _FOLLOWUP.search(text):
            break
    return None
