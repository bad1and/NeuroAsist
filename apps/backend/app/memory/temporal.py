"""Local temporal recall policy. Source time, never extraction time, anchors recall."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


TEMPORAL_CUE = re.compile(
    r"(?iu)\b(?:когда|во\s+сколько|сколько\s+времени\s+назад|"
    r"сегодня|вчера|позавчера|завтра|раньше|недавно|"
    r"(?:в\s+)?(?:прошлый|последний)\s+раз|последнее|до\s+перерыва|"
    r"до\s+этого|после\s+этого|потом|утром|дн[её]м|вечером|ночью|"
    r"when|what\s+time|yesterday|today|last\s+time|previously)\b"
)
_LATEST = re.compile(r"(?iu)\b(?:(?:в\s+)?(?:прошлый|последний)\s+раз|последнее|до\s+перерыва|last\s+time)\b")
_DAY = re.compile(r"(?iu)\b(позавчера|вчера|сегодня|yesterday|today)\b")
_DAY_OFFSETS = {"сегодня": 0, "today": 0, "вчера": 1, "yesterday": 1, "позавчера": 2}
_RECALL = re.compile(
    r"(?iu)\b(?:(?:чем|что|когда)\s+(?:я|мы)|что\s+(?:делал[аи]?|обсуждали)|"
    r"(?:помнишь|вспомни|напомни)\b.{0,50}\b(?:что|чем|когда|последн\w*|прошл\w*|перерыв\w*)|"
    r"последнее\s*,?\s*что\s+(?:делал|я)|"
    r"what\s+(?:did\s+)?(?:i|we))\b"
)
_FOLLOWUP = re.compile(
    r"(?iu)^\s*(?:(?:ну|а|нет|да|разумеется|конечно|именно|точнее|только|"
    r"я|имел|имела|в|виду|то|что|за|про|же)\b[\s,!.:—-]*)*"
    r"(?:сегодня|вчера|позавчера|today|yesterday)[\s?!.]*$"
)
_GENERIC = re.compile(
    r"(?iu)\b(?:чем|что|когда|я|мы|ты|мне|меня|у|нас|тобой|себе|вместе|занимал\w*|делал\w*|"
    r"обсуждал\w*|рассказывал\w*|последн\w*|прошл\w*|раз|сегодня|вчера|позавчера|"
    r"до|перерыва|в|за|ну|вот|тут|ходил|подскажи|пожалуйста|помнишь|вспомни|"
    r"напомни|разумеется|то|конечно|именно|не|а|нет|имел|виду|today|yesterday|last|time|"
    r"what|did|i|we)\b"
)


def parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def recall_subject(text: str) -> set[str]:
    question = _RECALL.search(text)
    if question:
        text = text[question.start():]
    return set(re.findall(r"(?u)\w{3,}", _GENERIC.sub(" ", text.casefold())))


def subject_matches(subject: set[str], text: str) -> bool:
    words = re.findall(r"(?u)\w{3,}", text.casefold())
    return not subject or any(word.startswith(term[:4]) for term in subject for word in words)


def inherit_temporal_question(text: str, previous_user_texts: list[str]) -> str:
    """An elliptical day correction inherits a user's subject, never Iris's guess."""
    if not _FOLLOWUP.fullmatch(text):
        return text
    for previous in reversed(previous_user_texts):
        if _FOLLOWUP.fullmatch(previous):
            continue
        if _RECALL.search(previous) and TEMPORAL_CUE.search(previous):
            subject = _DAY.sub("", _LATEST.sub("", previous)).strip(" ,.!?")
            day = _DAY.search(text).group(0)
            return f"{subject} {day}"
        # A new subject between the recall and its correction ends inheritance.
        return text
    return text


def is_temporal_followup(text: str) -> bool:
    return _FOLLOWUP.fullmatch(text) is not None


@dataclass(frozen=True)
class TemporalRecall:
    reference: datetime
    day: date | None = None
    latest: bool = False

    def source_day(self, timestamp: object) -> date | None:
        parsed = parse_timestamp(timestamp)
        return parsed.astimezone(self.reference.tzinfo).date() if parsed else None

    def relative_label(self, timestamp: object) -> str | None:
        day = self.source_day(timestamp)
        if day is None:
            return None
        delta = (self.reference.date() - day).days
        return {0: "сегодня", 1: "вчера", 2: "позавчера"}.get(delta, day.isoformat())

    def event_day(self, text: str, source_at: object) -> tuple[date | None, str]:
        """Explicit event dates outrank report dates; ambiguity stays a report."""
        source_day = self.source_day(source_at)
        dates = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text))
        if len(dates) == 1:
            try:
                return date.fromisoformat(next(iter(dates))), "event"
            except ValueError:
                pass
        days = {m.group(0).casefold() for m in _DAY.finditer(text)}
        if source_day and len(days) == 1:
            delta = _DAY_OFFSETS[next(iter(days))]
            return source_day - timedelta(days=delta), "event"
        return source_day, "report"


def temporal_recall(text: str, *, now: datetime | None = None) -> TemporalRecall | None:
    if not _RECALL.search(text) or not TEMPORAL_CUE.search(text):
        return None
    reference = now or datetime.now().astimezone()
    if reference.tzinfo is None:
        reference = reference.astimezone()
    day_matches = list(_DAY.finditer(text))
    if day_matches:
        # Accepted speech can contain several pending fragments. The user's
        # latest explicit correction overrides an earlier day's wording.
        delta = _DAY_OFFSETS[day_matches[-1].group(0).casefold()]
        return TemporalRecall(reference, reference.date() - timedelta(days=delta), bool(_LATEST.search(text)))
    if _LATEST.search(text):
        return TemporalRecall(reference, latest=True)
    return None
