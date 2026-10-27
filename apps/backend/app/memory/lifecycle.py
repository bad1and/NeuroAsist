"""Scope and freshness policy. Reading a memory is never new evidence for it."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime


_STYLE = re.compile(
    r"(?iu)\b(?:короче|кратк\w*|коротк\w*|длинн\w*|лаконич\w*|подробн\w*|разв[её]рнут\w*|"
    r"без\s+(?:воды|пояснений)|одн(?:им|о)\s+слов\w*|brief\w*|concise|short\w*|detail\w*)\b"
)
_COMMUNICATION = re.compile(
    r"(?iu)\b(?:говор\w*|отвеч\w*|ответ\w*|пиши|объясн\w*|распиши|расскаж\w*|"
    r"reply|replies|respond\w*|answer\w*|explain\w*)\b"
)
_LOCAL = re.compile(
    r"(?iu)\b(?:сейчас|сегодня|на\s+этот\s+раз|(?:в|для|на)\s+(?:этот|этом|этой|этого)\s+"
    r"(?:ответ\w*|раз\w*|задач\w*|диалог\w*|разговор\w*|чат\w*|игр\w*)|"
    r"this\s+(?:time|answer|chat|conversation|task)|for\s+now)\b"
)
_TURN = re.compile(r"(?iu)\b(?:эт(?:от|ом|ого)\s+ответ\w*|на\s+этот\s+раз|this\s+(?:time|answer))\b")
_DURABLE = re.compile(
    r"(?iu)\b(?:всегда|обычно|по\s+умолчанию|на\s+будущее|в\s+целом|вообще|отныне|"
    r"предпочитаю|люблю|ненавижу|раздраж\w*|не\s+переношу|терпеть\s+не\s+могу|мне\s+(?:нрав\w*|удобн\w*)|запомни|каждый\s+раз|always|usually|generally|"
    r"by\s+default|i\s+prefer|remember)\b"
)
_CONDITION = re.compile(
    r"(?iu)\b(?:когда|при|для|если|when|while|for)\s+([^.!?;:,\n]{2,120})"
)
_QUOTED = re.compile(
    r"(?iu)^\s*(?:[«\"“]|(?:он|она|они)\s+(?:говор\w*|сказал\w*|просил\w*)|"
    r"переведи|цитата|представь|translate|he\s+said|she\s+said)"
)
_RESET = re.compile(r"(?iu)\b(?:отвечай|говори|пиши)\s+(?:теперь\s+)?(?:обычно|нормально|свободно|как\s+раньше)\b")


@dataclass(frozen=True)
class StyleRequest:
    scope: str
    style: str
    condition: str = ""


def style_request(text: str) -> StyleRequest | None:
    """Literal communication requests only; uncertainty defaults to this dialogue."""
    if _QUOTED.search(text):
        return None
    if re.match(r"(?iu)^\s*(?:почему|зачем|какие|что\s+(?:значит|означает)|как\s+ты|ты\s+(?:всегда|обычно)|раньше|мой\s+прошлый|в\s+памяти|я\s+(?:когда-то|однажды|раньше|тогда)\b|why|you\s+always)\b", text):
        return None
    parts = [part.strip() for part in re.split(r"[.!?;\n]+", text) if part.strip()]
    if len(parts) > 1:
        requests = [request for part in parts if (request := style_request(part))]
        return requests[-1] if requests else None
    if _RESET.search(text):
        return StyleRequest("session", "normal")
    style = _STYLE.search(text)
    if not style or not (_COMMUNICATION.search(text) or re.fullmatch(r"(?iu)\s*(?:пожалуйста[, ]+)?короче[.! ]*", text)):
        return None
    value = style.group().casefold()
    direction = "detailed" if re.search(r"подроб|длинн|разв[её]рнут|detail", value) else "short"
    if re.search(r"(?iu)\b(?:не|перестань|хватит)\s+(?:говор\w*\s+|отвеч\w*\s+|люблю\s+)?(?:коротк\w*|кратк\w*|подробн\w*|длинн\w*|разв[её]рнут\w*)|\b(?:раздраж\w*|ненавижу|не\s+переношу|терпеть\s+не\s+могу)\b", text):
        direction = "short" if direction == "detailed" else "detailed"
    if re.search(r"(?iu)одн(?:им|о)\s+слов", value):
        direction = "one_word"
    if _LOCAL.search(text):
        return StyleRequest("turn" if _TURN.search(text) else "session", direction)
    condition = _CONDITION.search(text)
    if condition and condition_matches(condition[1], condition[1]):
        return StyleRequest("conditional", direction, condition[1].strip(" ,"))
    return StyleRequest("durable" if _DURABLE.search(text) else "session", direction)


def session_style_prompt(turns, current_text: str) -> str | None:
    """Replay direct session instructions without putting the whole history in a prompt."""
    texts = [str(row.get("corrected_content") or row.get("content") or "") for row in turns
             if row.get("role", "user") == "user" and row.get("dialogue_scope") not in {"ambient", "incomplete"}]
    if current_text and (not texts or texts[-1].strip() != current_text.strip()):
        texts.append(current_text)
    active = None
    for index, text in enumerate(texts):
        if scope_correction(text):
            active = None
        request = style_request(text)
        if request is None or request.scope == "conditional":
            continue
        if request.style == "one_word" and index != len(texts) - 1:
            # Long-running word games have their own task frame and end rules.
            continue
        if request.scope == "turn":
            if index == len(texts) - 1:
                active = request
        else:
            active = request
    if active is None:
        return None
    instruction = {
        "short": "Отвечай кратко, сохраняя нужные детали.",
        "detailed": "Отвечай подробно по существу.",
        "one_word": "Ответь одним словом, если задача допускает это.",
        "normal": "Используй обычную уместную длину ответа.",
    }[active.style]
    return "Текущий запрос пользователя о стиле: " + instruction + " Новая явная просьба важнее старого предпочтения; это не биографический факт."


def local_style_only(text: str) -> bool:
    parts = [part.strip() for part in re.split(r"[.!?;\n]+", text) if part.strip()]
    return bool(parts) and all(
        (request := style_request(part)) is not None and request.scope in {"session", "turn"}
        for part in parts
    )


def style_requests(text: str) -> list[StyleRequest]:
    if _QUOTED.search(text):
        return []
    return [request for part in re.split(r"[.!?;\n]+", text)
            if part.strip() and (request := style_request(part.strip())) is not None]


def scope_correction(text: str) -> bool:
    if _QUOTED.search(text):
        return False
    return bool(
        re.search(r"(?iu)\b(?:тогда|(?:имел|имела)\s+в\s+виду|та\s+просьба|это\s+относилось|не\s+просил\w*\s+всегда)\b", text)
        and re.search(r"(?iu)\b(?:только|лишь|не\s+(?:все|всегда|во\s+всех|постоянно|вообще))\b", text)
        and re.search(r"(?iu)\b(?:ответ\w*|диалог\w*|разговор\w*|просьб\w*)\b", text)
    )


def is_style_memory(values: dict) -> bool:
    return values.get("slot_key") == "user.prefers_response_length" or bool(
        _STYLE.search(str(values.get("value_text", "")))
        and _COMMUNICATION.search(str(values.get("value_text", "")))
        and values.get("slot_key") in {"user.preference", "user.note", "user.personal_fact", "user.constraint"}
    )


def parse_time(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    except (ValueError, TypeError):
        return None


# Soft review horizons describe changeability, not deletion deadlines.
_REVIEW_DAYS = {
    "user.current_mood": 1, "user.current_activity": 1,
    "user.current_goal": 45, "user.project": 60, "user.learning": 90,
    "user.schedule": 60, "user.habit": 120, "user.occupation": 180,
    "user.location": 180, "user.age": 180, "user.device": 365,
    "user.prefers_response_length": 120, "user.preference": 180,
}


def freshness(memory: dict, now: datetime | None = None) -> dict:
    """Use assertion time, never updated_at/access_count or extraction time."""
    lifecycle = dict(memory.get("metadata", {}).get("lifecycle", {}))
    confirmed = lifecycle.get("last_confirmed_at")
    observed = parse_time(confirmed)
    horizon = _REVIEW_DAYS.get(str(memory.get("slot_key")))
    if horizon is None:
        return {"state": "stable", "weight": 1.0, "last_confirmed_at": confirmed}
    if observed is None:
        return {"state": "unverified", "weight": .5, "last_confirmed_at": None}
    age = max(0, ((now or datetime.now(UTC)) - observed).total_seconds() / 86400)
    confirmations = min(4, max(1, int(lifecycle.get("confirmation_sessions", 1))))
    horizon *= 1 + .2 * (confirmations - 1)
    weight = max(.2, 1 / (1 + age / horizon))
    return {"state": "aging" if age > horizon else "recent", "weight": round(weight, 3),
            "last_confirmed_at": confirmed}


def condition_matches(condition: str, query: str) -> bool:
    # Communication words cannot activate a subject-specific preference.
    stop = {"когда", "если", "ответ", "отвеч", "говор", "подро", "корот", "кратк", "пожалу", "нужно", "объяс", "расск", "пользо", "очень", "только", "делу", "сути", "длинн", "лакон"}
    def terms(text):
        return {"код" if word.startswith("код") else word[:5] for word in re.findall(r"(?u)[^\W\d_]+", text.casefold())
                if len(word) >= 3 and not any(word.startswith(item) for item in stop)}
    a, b = terms(condition), terms(query)
    # A few common inflections/synonyms for communication preferences.
    groups = ({"код", "прогр", "pytho", "rust", "javas", "скрип", "react", "java", "cshar"},
              {"матем", "алгеб", "геоме", "уравн"})
    return bool(a & b or any(a & group and b & group for group in groups))
