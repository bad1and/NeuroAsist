"""Shared news intent for colloquial text and adjacent voice fragments."""
from __future__ import annotations

import re
from collections.abc import Iterable

NEWS_QUERY_PATTERN = re.compile(
    r"\b(?:новост\w*|дайджест|сводк\w*|главные\s+темы|news|headlines|"
    r"(?:что|че)\s+(?:там\s+)?(?:нового\s+)?в\s+мире|"
    r"(?:что|че)\s+(?:(?:там|сейчас)\s+)?происходит\s+в\s+мире|"
    r"(?:что|че|какая|какой|какие)\s+(?:(?:там|сейчас|сегодня|за|вообще|важные|главные)\s+){0,4}"
    r"(?:движух\w*|движ|событи\w*|творится|случил\w*|происходит)\s+"
    r"(?:сейчас\s+)?(?:в\s+мире|на\s+планете)|"
    r"чем\s+(?:сейчас\s+)?живет\s+мир)\b", re.I,
)


def news_request_text(text: str, messages: Iterable = ()) -> str | None:
    normalized = text.replace("ё", "е")
    if NEWS_QUERY_PATTERN.search(normalized):
        return text
    # Only complete the immediately preceding user turn. A distant news topic
    # must not turn an unrelated greeting or personal question into retrieval.
    if not re.fullmatch(r"\s*(?:происходит|сейчас происходит|происходит сейчас)[.!? ]*", normalized, re.I):
        return None
    users = [m.content for m in messages if getattr(m, "role", None) == "user"]
    if users and users[-1].strip() == text.strip():
        users.pop()
    if users and NEWS_QUERY_PATTERN.search(users[-1].replace("ё", "е")):
        return f"{users[-1]} {text}"[:400]
    return None
