"""Conservative search planning for explicit requests, without a model roundtrip."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable

from apps.backend.app.environment.retrieval import internet_forbidden, normalize_entity, sensitive_query, terms
from apps.backend.app.agents.character.turn_intent import analyze_dialogue_turn


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    fallback_query: str | None = None
    preferred_domains: tuple[str, ...] = ()
    force_refresh: bool = False
    mode: str = "web"
    since: str = ""
    until: str = ""
    reason: str = "explicit"
    entity: str = ""
    goal: str = ""


def supplied_material(text: str) -> bool:
    """An attached body is input to work on, not an enormous search query."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    marked_body = bool(re.search(r"(?:вот|держи|присылаю|прислал).{0,20}(?:текст|слова)|\[(?:куплет|припев|verse|chorus)|```", text, re.I))
    return len(text) >= 160 and (len(lines) >= 6 or marked_body)


def material_continuation(text: str) -> bool:
    return len(text) < 160 and bool(
        re.search(r"(?:до\s+(?:конца|полной)|полностью|(?:второй|третий).{0,15}куплет|остальн\w*.{0,15}(?:куплет|част)|продолжи.{0,15}(?:текст|песн))", text, re.I)
        or re.fullmatch(r"\s*(?:(?:ну|а|давай|еще|ещё)\s+)*(?:дальше|продолжай|продолжи|продолжение)[.!? ]*", text, re.I)
    )


def query_anchors(value: str) -> set[str]:
    generic = terms("текст песни песня трек куплет первый второй третий полностью полный слова исполнитель найти прочитать спеть напеть подробности song lyrics text verse full first second third details")
    return terms(value) - generic


def refinement_preserves_subject(original: str, refined: str, entity: str = "") -> bool:
    """Keep names/versions fixed while allowing a better phrasing or language."""
    original = re.sub(r"\b(?:site|after|before):\S+", "", original, flags=re.I)
    for version in re.findall(r"\b\d+(?:\.\d+)+(?:[a-z][a-z0-9-]*)?\b", original, re.I):
        if not re.search(r"(?<![\w.])" + re.escape(version) + r"(?![\w.])", refined, re.I):
            return False
    for quoted in re.findall(r'[«"]([^»"]+)[»"]', original):
        if normalize_entity(quoted) not in normalize_entity(refined):
            return False
    if entity:
        anchors = query_anchors(entity)
    else:
        # Search wording is replaceable; product names, quoted titles and exact
        # error/version identifiers are not. With no named subject, stay strict.
        generic = terms("Ошибка установка установить исправить причина решение почему где когда инструкция Error install installation fix solution failed failure troubleshooting package documentation details official release announcement latest version")
        names = re.findall(r"\b(?:[A-ZА-ЯЁ][\w.+-]*|[a-z][a-z0-9.+-]*)\b", original)
        anchors = set().union(*(terms(name) for name in names)) - generic if names else set()
        for quoted in re.findall(r'[«"]([^»"]+)[»"]', original):
            anchors.update(query_anchors(quoted))
        anchors.update(word for word in terms(original) if word.isdigit() and not re.fullmatch(r"20\d{2}", word))
        if not anchors:
            anchors = query_anchors(original)
    return bool(anchors) and anchors.issubset(terms(refined))


_COMMAND = re.compile(r"\b(?:найди|поищи|поискать|погугли|загугли|погуглить|гугли|ищи|(?:посмотри|глянь|проверь)\s+в\s+(?:интернете|инете|сети)|search\s+(?:for|the\s+web)|look\s+up)\b", re.I)
_FRESH = re.compile(r"\b(?:когда\s+(?:выйдет|выходит|выход|релиз)|дата\s+(?:выхода|релиза)|когда.{0,80}\bрелиз|(?:актуальн\w*|последн\w*|новейш\w*|текущ\w*)\s+верси\w*|какая.{0,40}\bверсия|сколько\s+сейчас\s+стоит|when.{0,80}\b(?:release|launch)|latest\s+version)\b", re.I)
_LOCAL = re.compile(r"\b(?:в\s+(?:этом|моем|данном)\s+(?:коде|тексте|файле)|перепиши|отредактируй|переведи|исправь\s+(?:код|текст)|(?:как|почему|зачем)\s+(?:работает|работал|устроен)|(?:как|почему)\s+найти|(?:ошибк\w*|опечатк\w*)\s+в\s+(?:код\w*|текст\w*)|(?:ты|она)\s+(?:умеешь|умеет|может)\s+(?:искать|найти)|я\s+(?:сам\s+)?(?:найду|поищу|погуглю)|(?:не|не\s+надо|не\s+нужно)\s+(?:найди|поищи|погугли))\b", re.I)
_FOLLOWUP = re.compile(r"\b(?:ты.{0,35}\bнайди|найди\s+не\s+я|(?:ну\s+)?(?:и\s+)?что\s+там|что\s+с\s+поиском|ты.{0,60}\b(?:ищешь|искать)|але|алло|ты\s+тут|(?:найди|поищи|проверь)\s+(?:это|еще\s+раз|заново|лучше)|ищи\s+(?:ты|сама)|поищи\s+(?:ты|сама))\b", re.I)
_FILLER = re.compile(r"\b(?:пожалуйста|плиз|ирис|iris|ты|сама|сам|мне|нам|это|то|не|я|нет|ну|так|с|в|и|там|данные|информацию|информация|что|же|еще|раз|заново|лучше|нормально|давай|теперь|уже|бля|блять|смысле|ебаный|свет|поиск|поиском)\b", re.I)
_RECENT = re.compile(r"\b(?:последн\w*|нов\w*|свеж\w*)\s+(?:вышедш\w*\s+)?(?:перс\w*|геро\w*|агент\w*|обновлен\w*|патч\w*)|\b(?:latest|newest)\s+(?:hero|character|agent|update)\b", re.I)
_CURRENT = re.compile(r"(?:свеж\w*|последн\w*|актуальн\w*).{0,15}\b(?:новост\w*|информац\w*|данн\w*)|(?:что|че|чё).{0,60}\bпроизошл\w*|latest\s+(?:news|information)", re.I)
_REFERENCE = re.compile(r"\b(?:их|его|нее|него|нему|ним|ней|них)\b", re.I)


def _clean_query(text: str) -> str:
    text = normalize_entity(text)
    text = re.sub(r"\b(?:дата[ -]?центр)(?:ами|ом|ов|ы|а|е)?\b", "дата-центры", text, flags=re.I)
    text = re.sub(r"\b(?:у\s+нас|получается|по\s+нему|по\s+ним|что\s+там|че\s+там)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:а|че|чё|какие|какая|какой|какое|их|его|него|нему|ним|них)\b", " ", text, flags=re.I)
    return " ".join(_FILLER.sub(" ", text).split()).strip(" ,.!?:")[:300]


def explicit_query_revision(text: str, previous_query: str, recent_messages=()) -> SearchRequest | None:
    """A literal replacement outranks the assistant's earlier search hypotheses."""
    if not previous_query or internet_forbidden(text) or sensitive_query(text):
        return None
    text = " ".join(text.split())
    match = re.search(
        r"(?iu)(?:(?:просто|только)\s+(?:найди|поищи|ищи)|(?:найди|поищи|ищи)\s+(?:просто|только)|(?:запрос|поиск)\s*[:—])\s*(.+)$", text,
    )
    if match is None and re.search(r"(?iu)\b(?:убери|исключи|запрос|поискать|поищи)\b", " ".join(
        m.content for m in list(recent_messages)[-4:] if getattr(m, "role", None) == "user"
    )):
        match = re.search(r"(?iu)\bпросто\s+(.+)$", text)
    if match is None:
        return None
    query = re.sub(r"(?iu)\s+(?:вс[её]|вот и вс[её]|и вс[её])[.!? ]*$", "", match[1]).strip(' .!?«»"')
    if len(terms(query)) < 2 or len(query) > 300 or sensitive_query(query):
        return None
    return SearchRequest(normalize_entity(query), force_refresh=True, reason="query_revision")


_DETAIL = re.compile(r"^\s*(?:(?:вот|прям|еще|ну|это|не|нет|да|а|давай|точнее|вернее|я имел в виду)\s+)*(?:сейчас|в\s+этом\s+году|(?:за\s+)?(?:вчера|сегодня)|недавно|другой\s+(?:вариант|анекдот)|за\s+(?:неделю|месяц))\b", re.I)
_RETRY = re.compile(r"\b(?:заново|еще\s+раз|по\s+другому|лучше|другой)\b", re.I)
_ENTITY = re.compile(r"\b(?:deadlock|gta\s+(?:[456]|iv|v|vi)|python|valorant|minecraft|r\.?e\.?p\.?o\.?)\b", re.I)
_EVENT = re.compile(r"выбор\w*|госдум\w*|государственн\w*\s+дум\w*|чемпионат\w*|кубок\w*|world\s*cup|election", re.I)
_OUTCOME = re.compile(r"\b(?:кто\s+(?:выиграл|победил|победитель)|результат\w*|итоги)\b", re.I)

# Intent is independent of the words following a command. In spoken dialogue
# the subject is often in a previous turn and the command ends in filler.
_LOOKUP = re.compile(r"\b(?:найти|почитай|почитать|прочитай|узнай|проверь|посмотри|глянь)\b", re.I)
_CHANGING = re.compile(r"последн\w*.{0,35}(?:песн|трек|релиз|альбом|верси)|(?:песн|трек|релиз).{0,35}последн|(?:по)?удал\w*.{0,90}(?:музык|платформ|трек)|(?:музык|платформ|трек).{0,90}(?:по)?удал|(?:цен\w*|стоимост\w*|курс\w*).{0,25}(?:сейчас|сегодня)|биограф", re.I)
_ACCEPT = re.compile(r"^\s*(?:ну\s+)?(?:давай(?:\s+ка)?|да|ага|хорошо|окей)(?:\s+(?:еще\s+раз|поищи|проверь))?[.!? ]*$", re.I)
_EMPTY_TAIL = re.compile(r"\b(?:в|принципе|да|попробуй|можешь|можно|вообще|подробнее|его|нее|него|это|такого|исполнителя|исполнитель|знаешь|ли|пожалуйста|найти|почитать|почитай|узнай|проверь)\b", re.I)


def contextual_search(text: str) -> bool:
    return bool(factual_detail_question(text) or _FOLLOWUP.search(text) or _RETRY.search(text) or _ACCEPT.fullmatch(text) or _DETAIL.search(text) or
                ((_LOOKUP.search(text) or _CHANGING.search(text)) and re.search(r"\b(?:его|нее|него|нем|ней|это|еще|заново)\b", text, re.I)))


def factual_detail_question(text: str) -> bool:
    """A missing field in an adjacent report, not every sentence mentioning it."""
    return len(text) <= 300 and not re.search(r"(?iu)\b(?:кстати|сменим тему|в моем коде|в этом тексте)\b", text) and bool(re.search(
        r"(?iu)\b(?:по каким|каки[емх]|како[йем]|какая|какую)\b.{0,60}\b(?:объект\w*|цел\w*|причин\w*|последств\w*)\b|"
        r"\b(?:почему|из-за чего|что (?:именно )?пострадало)\b", text))


def requires_article_evidence(text: str) -> bool:
    return bool(re.search(r"(?iu)\b(?:причин\w*|цел[ьиь]\w*|объект\w*|последств\w*|почему|из-за чего|по каким)\b", text))


def medical_fact_request(text: str) -> SearchRequest | None:
    """Public educational facts only; never include a personal disclosure."""
    if internet_forbidden(text) or sensitive_query(text):
        return None
    fact = re.search(r"(?iu)\b(?:факт\w*|что такое|как работает|что значит|почему|объясни)\b", text)
    medical_topic = re.compile(r"(?iu)\b(?:диабет\w*|инсулин\w*|гипогликеми\w*|гипергликеми\w*|астм\w*|мигрен\w*|вакцин\w*|псориаз\w*|онкологи\w*|рак(?:а|е|ом)?|медицин\w*)\b")
    subject = (medical_topic.search(text, fact.start()) or medical_topic.search(text)) if fact else None
    if not subject or not fact:
        return None
    topic = "диабет" if subject[0].casefold().startswith("диабет") else subject[0]
    detail = "медовый месяц фаза" if re.search(r"(?iu)медов\w*\s+месяц", text) else "интересные факты" if re.search(r"(?iu)факт", text) else "объяснение"
    return SearchRequest(f"{topic} {detail}", preferred_domains=("diabetes.org", "niddk.nih.gov", "who.int") if topic == "диабет" else ("who.int", "nhs.uk", "nih.gov"),
                         reason="medical_fact", goal=f"{topic} {detail}")


def search_subject(text: str) -> str:
    """Extract a user-supplied name, never an assistant's invented biography."""
    if internet_forbidden(text) or sensitive_query(text):
        return ""
    normalized = normalize_entity(text)
    entity = _ENTITY.search(normalized)
    if entity:
        return entity[0]
    match = re.search(r"(?:исполнител\w*|рэпер\w*|певец|групп\w*|песню)\s+([\w. -]{2,70})", text, re.I)
    if match:
        name = re.split(r"\b(?:если|котор|ну|можешь)\b", match[1], maxsplit=1, flags=re.I)[0]
        if re.match(r"(?:с |котор|какой|такой|этот|необычн)", name, re.I):
            return ""
        return name.strip(" .?!")[:70]
    if re.search(r"\bлсп\b|\blsp\b", text, re.I):
        return "ЛСП"
    return ""


def _conversation_request(text: str, messages: Iterable) -> SearchRequest | None:
    active = bool(_COMMAND.search(text) or _LOOKUP.search(text) or _CHANGING.search(text) or _ACCEPT.fullmatch(text) or _RETRY.search(text))
    if not active:
        return None
    # Complete fresh questions do not need a product allowlist.
    if _CHANGING.search(text) and not re.search(r"\b(?:его|нее|него|у него)\b", text, re.I):
        query = " ".join(_EMPTY_TAIL.sub(" ", _FILLER.sub(" ", text)).split()).strip(" ,.!?:")
        if len(terms(query)) >= 2:
            return SearchRequest(query[:300], reason="current_fact")
    command = _COMMAND.search(text) or _LOOKUP.search(text)
    tail = text[command.end():] if command else ""
    tail = " ".join(_EMPTY_TAIL.sub(" ", _FILLER.sub(" ", tail)).split()).strip(" ,.!?:")
    if tail and _meaningful(tail) and not re.search(r"биограф|географ|последн", tail, re.I):
        return None  # Existing self-contained query handling owns this case.
    subject = ""
    prior_query = ""
    track = ""
    for message in reversed(list(messages)[-8:]):
        if getattr(message, "role", None) != "user" or message.content.strip() == text.strip():
            continue
        previous = message.content
        if internet_forbidden(previous) or sensitive_query(previous) or re.fullmatch(r"\s*(?:привет|ладно|не надо|да не не надо)[.!? ]*", previous, re.I):
            return None
        subject = search_subject(previous)
        song = re.search(r"называется\s+(?:трек\s+)?([\w -]{2,50})", previous, re.I) or re.search(r"трек\s+([\w -]{2,50})", previous, re.I)
        if song and not track:
            track = song[1].strip()
        if _CHANGING.search(previous) and not prior_query:
            prior_query = previous
        if subject:
            break
        if re.search(r"\b(?:кстати|сменим тему|теперь о|давай про)\b|(?:расскажи|поговорим).{0,12}\b(?:про|о)\b", previous, re.I):
            break
    if prior_query and _ACCEPT.fullmatch(text):
        recovered = _conversation_request(prior_query, ()) or _request(prior_query)
        return replace(recovered, force_refresh=bool(_RETRY.search(text)), reason="continuation") if recovered else None
    if not subject:
        return None
    if _ENTITY.search(subject):
        return None  # Preserve the existing version/event/detail recovery.
    fact = "биография" if re.search(r"биограф|географ|почита", text, re.I) else "последняя песня дата релиза" if _CHANGING.search(text) else ""
    query = " ".join(filter(None, (subject, fact, track if not fact else "")))
    return SearchRequest(query[:300], force_refresh=bool(_RETRY.search(text)), reason="continuation", entity=subject)


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


def search_requested(text: str, recent_messages: Iterable = ()) -> bool:
    text = text.replace("ё", "е")
    if analyze_dialogue_turn(text, recent_messages).suppress_lookup:
        return False
    return not (internet_forbidden(text) or sensitive_query(text) or _LOCAL.search(text)) and bool(
        medical_fact_request(text) or factual_detail_question(text) or _COMMAND.search(text) or _LOOKUP.search(text) or _CHANGING.search(text) or _RETRY.search(text) or _ACCEPT.fullmatch(text) or _FRESH.search(text) or _RECENT.search(text) or _CURRENT.search(text) or _FOLLOWUP.search(text) or _DETAIL.search(text) or (_EVENT.search(text) and _OUTCOME.search(text)))


def needs_query_planner(text: str, recent_messages: Iterable = ()) -> bool:
    """An explicit but unresolved request must not become an invented query."""
    recent_messages = list(recent_messages)
    if analyze_dialogue_turn(text, recent_messages).suppress_lookup:
        return False
    users = [m for m in recent_messages if getattr(m, "role", None) == "user"][-8:]
    explicit = bool(_COMMAND.search(text) or _LOOKUP.search(text) or _CHANGING.search(text) or _FRESH.search(text) or _RECENT.search(text) or _CURRENT.search(text) or (_EVENT.search(text) and _OUTCOME.search(text)))
    contextual = bool(users and (_DETAIL.search(text) or _FOLLOWUP.search(text)) and
                      any(_COMMAND.search(m.content) or _FRESH.search(m.content) or _RECENT.search(m.content) or _event_request(m.content) for m in users))
    accepted = analyze_dialogue_turn(text, recent_messages).accepts_lookup
    return search_requested(text, recent_messages) and (explicit or contextual or accepted) and plan_search(text, recent_messages) is None


def _meaningful(query: str) -> bool:
    return bool(_ENTITY.search(query) or re.fullmatch(r"(?:gonefludd|lsp)", normalize_entity(query)) or len(terms(query)) >= 2)


def _fact(text: str) -> str:
    if _RECENT.search(text):
        return "последний новый герой" if re.search(r"перс|геро|агент|hero|character|agent", text, re.I) else "последнее обновление"
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
    command = _COMMAND.search(text) or _LOOKUP.search(text)
    if not command and not (_FRESH.search(text) or _RECENT.search(text) or _CURRENT.search(text)):
        return None
    query = text[command.end():] if command else text
    if command and not _EMPTY_TAIL.sub("", _FILLER.sub("", query)).strip(" ,.!?:"):
        return None
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
    query = _clean_query(query)
    query = re.sub(r"\b(?:в\s+)?(?:инете|интернете|можешь|прям|должно\s+быть)\b", " ", query, flags=re.I)
    query = " ".join(query.split()).strip(" ,.!?:")
    if _CURRENT.search(text):
        query = re.sub(r"\bпроизошл\w*\b", "новости", query, flags=re.I)
    entity = _ENTITY.search(query)
    if entity and _RECENT.search(query):
        period = " ".join(re.findall(r"\b(?:вчера|сегодня|недавно)\b", query))
        query = f"{entity[0]} {_fact(query)} {period}".strip()
    if not entity and re.search(r"(?:че|что)[ -]нибудь|вернемся к этому вопросу|\bдопустим\b", query, re.I):
        return None
    if not (_meaningful(query) or (_CURRENT.search(text) and terms(query))) or (not command and not (_ENTITY.search(query) or _CURRENT.search(text))):
        return None
    return SearchRequest(query, force_refresh=bool(_RETRY.search(text)), mode="news" if _CURRENT.search(text) else "web")


def plan_search(user_text: str, recent_messages: Iterable = ()) -> SearchRequest | None:
    """Use the current request, or a recent user topic for an explicit correction.

    Never turn assistant prose, memory, or an entire transcript into a query.
    Generic greetings and search troubleshooting do not activate retrieval.
    """
    if supplied_material(user_text) or internet_forbidden(user_text) or sensitive_query(user_text) or _LOCAL.search(user_text):
        return None
    recent_messages = list(recent_messages)
    if analyze_dialogue_turn(user_text, recent_messages).suppress_lookup:
        return None
    medical = medical_fact_request(user_text)
    if medical is not None:
        return medical
    user_text = user_text.replace("ё", "е")
    if (re.search(r"(?iu)\b(?:свеж\w*|нов\w*|актуальн\w*|обнови)\b.{0,35}\bмем\w*\b|\bмем\w*\b.{0,35}\b(?:сейчас|сегодня|недавно|нов\w*)\b", user_text)
            and (analyze_dialogue_turn(user_text, recent_messages).kind == "request"
                 or re.match(r"(?iu)^\s*(?:(?:ну|а|давай)\s+)*(?:обнови|покажи|пришли|кинь|дай|пошути)\b", user_text))):
        # Public topic only. Never turn the user's actual story into a query.
        month = datetime.now().astimezone().strftime("%Y-%m")
        return SearchRequest(f"свежие мемы Рунета СНГ {month} значение", reason="meme_refresh")
    song = re.search(r"\b(?:спой|спеть|напеть|напой)\s+(?:пожалуйста\s+)?(?:песню\s+|трек\s+)?(.+)", user_text, re.I)
    if song:
        title = re.split(r"\b(?:если|пожалуйста|можешь)\b", song[1], maxsplit=1, flags=re.I)[0].strip(' .!?«»"')
        title = normalize_entity(title)
        if len(title) <= 100 and query_anchors(title) and not re.fullmatch(r"(?:это|его|ее|её|мне|что нибудь|что-нибудь|до конца)", title, re.I):
            return SearchRequest(title + " текст песни", entity=title, goal=user_text, reason="source_content")
    conversation_request = _conversation_request(user_text, recent_messages)
    if conversation_request is not None:
        return conversation_request
    request = _request(user_text)
    if _REFERENCE.search(user_text) and request is not None:
        for message in reversed(recent_messages[-8:]):
            if getattr(message, "role", None) != "user":
                continue
            if internet_forbidden(message.content) or sensitive_query(message.content):
                break
            if _REFERENCE.search(message.content):
                continue
            prior = _request(message.content)
            if prior is None:
                break
            # Inherit only overlapping topics; a different named request stands alone.
            if query_anchors(request.query) & query_anchors(prior.query):
                query = " ".join(dict.fromkeys((prior.query + " " + request.query).split()))[:300]
                return replace(prior, query=query, force_refresh=bool(_RETRY.search(user_text)), reason="continuation")
            break
    users = [m for m in recent_messages if getattr(m, "role", None) == "user"][-8:]
    # A request for a different anecdote needs the quoted fragment, not just
    # the generic word 'анекдот'. Other self-contained requests stand alone.
    contextual = bool(_RETRY.search(user_text) and re.search(r"анекдот|вариант", user_text, re.I))
    if request is not None and not contextual:
        return request
    if len(user_text) > 300 or not search_requested(user_text, recent_messages):
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
