"""Small, deterministic evidence helpers shared by storage and memory policy.

Fingerprints contain no source text. They identify an assertion in its original
message, rather than globally banning a fact the user may later state again.
"""
from __future__ import annotations

import hashlib
import re


_STOP = {"это", "для", "меня", "мне", "мой", "моя", "мои", "есть", "без", "что", "как",
         "очень", "только", "уже", "теперь", "больше", "также", "ещё", "еще", "the", "and",
         "with", "user", "пользователь", "пользователя"}
_STOP_PREFIXES = ("любл", "люблю", "предпочит", "нрав", "запомн", "сохран", "пользоват")


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.casefold().replace("ё", "е")))


def terms(text: str) -> set[str]:
    return {word[:6] for word in normalize(text).split()
            if len(word) >= 3 and word not in _STOP and not word.startswith(_STOP_PREFIXES)}


def digest(source_id: str, value: str) -> str:
    return hashlib.sha256((source_id + "\0" + value).encode("utf-8")).hexdigest()


def units(text: str) -> list[str]:
    parts = re.split(r"[.!?;\n]+|,?\s+(?:а\s+ещ[её]|и\s+ещ[её]|а\s+также)\s+|"
                     r",\s*(?:а|но)\s+|\s+и\s+(?=(?:я|мне|у\s+меня|предпочитаю|люблю)\b)", text,
                     flags=re.IGNORECASE)
    return [part.strip() for part in parts if part.strip()]


def matching_units(text: str, value: str) -> list[str]:
    wanted = terms(value)
    scored = [(len(wanted & terms(part)), part) for part in units(text)]
    best = max((score for score, _ in scored), default=0)
    return [part for score, part in scored if score == best and score > 0]


def fingerprint(source_id: str, value: str, source_text: str) -> dict:
    return {"value": digest(source_id, normalize(value)),
            "units": [digest(source_id, normalize(part)) for part in matching_units(source_text, value)],
            "terms": sorted(digest(source_id, term) for term in terms(value))}


def matches_fingerprint(source_id: str, value: str, source_text: str, saved: dict, *, single: bool = False,
                        derived: bool = False) -> bool:
    if single:
        # One canonical property per source cannot be reintroduced merely by
        # inventing an alias for its value. A new message remains independent.
        return True
    candidate = fingerprint(source_id, value, source_text)
    if candidate["value"] == saved.get("value"):
        return True
    shared_unit = bool(set(candidate["units"]) & set(saved.get("units", [])))
    a, b = set(saved.get("terms", [])), set(candidate["terms"])
    if not a or not b:
        return single and shared_unit
    overlap = len(a & b)
    # A derived summary includes surrounding facts: use containment, never let
    # extra prose hide a forgotten assertion. Separate sibling facts still need
    # their own matching evidence terms.
    similar = overlap / len(a) >= .8 if derived else overlap / len(a | b) >= .5
    return shared_unit and (single or similar)
