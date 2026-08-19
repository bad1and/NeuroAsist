from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


DEFAULT_PRONUNCIATIONS = {
    "NeuroAsist": "Нейро Асист",
    "OpenAI": "Оупен Эй Ай",
    "GitHub": "Гитхаб",
    "YouTube": "Ютуб",
    "Discord": "Дискорд",
    "как-то": "к+ак-то",
    "всё-таки": "вс+ё-т+аки",
    "кто-нибудь": "кт+о-ниб+удь",
    "по-прежнему": "по-пр+ежнему",
}

_COMBINING_ACUTE = "\u0301"
_CYRILLIC_VOWELS = frozenset("АЕЁИОУЫЭЮЯаеёиоуыэюя")
_WORD_HYPHENS = "\u2010\u2011\u2012\u2013"


def normalize_tts_orthography(text: str) -> str:
    """Normalize typography without splitting hyphenated words into speech tokens."""
    value = unicodedata.normalize("NFC", text).replace("\u00ad", "")
    value = value.replace("\u00a0", " ")
    value = re.sub(rf"(?<=\w)[{_WORD_HYPHENS}](?=\w)", "-", value)
    value = re.sub(r"\s*[—–]\s*", " — ", value)
    return " ".join(value.split())


def normalize_pronunciation_target(value: str) -> str:
    """Accept combining-acute and legacy ``к+ак-то`` stress notation."""
    normalized = unicodedata.normalize("NFC", value).replace("\u00ad", "")
    output: list[str] = []
    for char in normalized:
        if char == _COMBINING_ACUTE:
            if output and output[-1] in _CYRILLIC_VOWELS:
                vowel = output.pop()
                output.extend(("+", vowel))
            continue
        output.append(char)
    return "".join(output)


def load_pronunciations(path: Path) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            json.dumps({"pronunciations": DEFAULT_PRONUNCIATIONS}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = payload.get("pronunciations", payload)
        if not isinstance(values, dict):
            raise ValueError("pronunciations must be an object")
        custom = {str(key).strip(): str(value).strip() for key, value in values.items() if str(key).strip() and str(value).strip()}
    except (OSError, ValueError, json.JSONDecodeError):
        custom = {}
    return _merge_pronunciations(custom)


def save_pronunciations(path: Path, entries: dict[str, str]) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {
        str(key).strip(): str(value).strip()
        for key, value in entries.items()
        if str(key).strip() and str(value).strip()
    }
    path.write_text(
        json.dumps({"pronunciations": cleaned}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _merge_pronunciations(cleaned)


def _merge_pronunciations(custom: dict[str, str]) -> dict[str, str]:
    """Merge user entries case-insensitively so they can override built-ins."""
    merged = dict(DEFAULT_PRONUNCIATIONS)
    existing_keys = {source.casefold(): source for source in merged}
    for source, replacement in custom.items():
        previous = existing_keys.get(source.casefold())
        if previous is not None and previous != source:
            merged.pop(previous, None)
        merged[source] = replacement
        existing_keys[source.casefold()] = source
    return merged


def apply_pronunciations(text: str, entries: dict[str, str]) -> str:
    for source in sorted(entries, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        text = pattern.sub(entries[source], text)
    return text


def split_pronunciation_overrides(text: str, entries: dict[str, str]) -> list[tuple[str, bool]]:
    """Split text into user-controlled and automatic-accentor regions.

    A combined matcher makes the longest user entry win and avoids sending its
    replacement back through the automatic accentor.
    """
    if not entries:
        return [(text, False)]
    source_by_fold: dict[str, str] = {}
    replacement_by_fold: dict[str, str] = {}
    for source, replacement in entries.items():
        folded = source.casefold()
        source_by_fold.setdefault(folded, source)
        replacement_by_fold[folded] = replacement
    sources = [source_by_fold[key] for key in sorted(source_by_fold, key=lambda key: len(source_by_fold[key]), reverse=True)]
    if not sources:
        return [(text, False)]
    pattern = re.compile(
        rf"(?<!\w)(?P<source>{'|'.join(re.escape(source) for source in sources)})(?!\w)",
        re.IGNORECASE,
    )
    output: list[tuple[str, bool]] = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            output.append((text[cursor : match.start()], False))
        key = match.group("source")
        replacement = replacement_by_fold.get(key.casefold(), key)
        output.append((normalize_pronunciation_target(replacement), True))
        cursor = match.end()
    if cursor < len(text):
        output.append((text[cursor:], False))
    return output or [(text, False)]
