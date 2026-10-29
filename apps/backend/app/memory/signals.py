"""Cheap scheduling signals; semantic memory decisions belong to the model."""
import re


MEMORY_CORRECTION_CUE = re.compile(
    r"(?iu)(?:"
    r"\bне\s+[^.!?\n]{1,120}?\s*,?\s+а\s+[^.!?\n]+"
    r"|\b(?:на\s+самом\s+деле|теперь\s+я|я\s+больше\s+не|зови\s+меня|исправ\w*)\b"
    r"|\bнет[, :]+(?:я|меня|мой|моя|мо[её]|теперь|это|у)\b"
    r")"
)

ACTIVITY_COMPLETION_CUE = re.compile(
    r"(?iu)\b(?:уже\s+(?:вс[её]\s+)?(?:исправ\w*|пофикс\w*|сделал\w*|закончил\w*)|"
    r"убрал\w*\b.{0,35}\bконфликт\w*)\b"
)


PERSONAL_EVENT_CUE = re.compile(
    r"(?iu)^\s*(?:(?:я|мы|сегодня|вчера|недавно|наконец|теперь)\s+)*"
    r"(?:уволил(?:ся|ась)|переехал[аи]?|переехала|устроил(?:ся|ась)\s+на\s+работу|"
    r"бросил[аи]?\s+(?:курить|пить)|купил[аи]?\s+(?:ноутбук|компьютер|телефон|машину|квартиру)|"
    r"родил(?:ся|ась)\s+(?:сын|дочь|реб[её]нок)|закончил[аи]?\s+(?:университет|школу|колледж|курс)|"
    r"развелись|разв[её]л(?:ся|ась)|женил(?:ся|ась)|вышла\s+замуж|"
    r"перестал[аи]?\s+(?:курить|пить|работать|изучать)|больше\s+не\s+(?:люблю|работаю|живу))\b"
)


def personal_event(text: str) -> bool:
    """Schedule a small Russian event; the extractor still decides its meaning."""
    return "?" not in text and bool(PERSONAL_EVENT_CUE.search(text))
