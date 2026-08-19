"""Russian text preparation for TeraTTSv2.

TeraTTSv2 requires balanced language tags.  The application deliberately sends
one Russian span for Iris instead of mixing ``<ru>`` and ``<en>`` fragments:
technical English is rendered through a small pronunciation lexicon, while
ordinary numbers are left for the model's native ``num2words`` expansion.
"""

from __future__ import annotations

import re
import unicodedata


_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_MONTH_RE = "(" + "|".join(_MONTHS) + ")"

_DAY_GENITIVE = {
    1: "первого", 2: "второго", 3: "третьего", 4: "четвёртого",
    5: "пятого", 6: "шестого", 7: "седьмого", 8: "восьмого",
    9: "девятого", 10: "десятого", 11: "одиннадцатого",
    12: "двенадцатого", 13: "тринадцатого", 14: "четырнадцатого",
    15: "пятнадцатого", 16: "шестнадцатого", 17: "семнадцатого",
    18: "восемнадцатого", 19: "девятнадцатого", 20: "двадцатого",
    21: "двадцать первого", 22: "двадцать второго", 23: "двадцать третьего",
    24: "двадцать четвёртого", 25: "двадцать пятого", 26: "двадцать шестого",
    27: "двадцать седьмого", 28: "двадцать восьмого", 29: "двадцать девятого",
    30: "тридцатого", 31: "тридцать первого",
}
_DAY_ACCUSATIVE = {
    day: word.replace("-ого", "-ое").replace("-его", "-ее").replace("ого", "ое").replace("его", "ее")
    for day, word in _DAY_GENITIVE.items()
}
_DAY_DATIVE = {
    1: "первому", 2: "второму", 3: "третьему", 4: "четвёртому",
    5: "пятому", 6: "шестому", 7: "седьмому", 8: "восьмому",
    9: "девятому", 10: "десятому", 11: "одиннадцатому",
    12: "двенадцатому", 13: "тринадцатому", 14: "четырнадцатому",
    15: "пятнадцатому", 16: "шестнадцатому", 17: "семнадцатому",
    18: "восемнадцатому", 19: "девятнадцатому", 20: "двадцатому",
    21: "двадцать первому", 22: "двадцать второму", 23: "двадцать третьему",
    24: "двадцать четвёртому", 25: "двадцать пятому", 26: "двадцать шестому",
    27: "двадцать седьмому", 28: "двадцать восьмому", 29: "двадцать девятому",
    30: "тридцатому", 31: "тридцать первому",
}
_VERSION_DIGITS = {
    "0": "ноль", "1": "один", "2": "два", "3": "три", "4": "четыре",
    "5": "пять", "6": "шесть", "7": "семь", "8": "восемь", "9": "девять",
}

_TECH_LEXICON: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in {
        r"\bTeraTTS\s*[vV]?2\b": "Тера ТТС версия два",
        r"\bTeraTTS\b": "Тера ТТС",
        r"\bFastAPI\b": "Фаст+АПИ",
        r"\bWebSockets?\b": "Вебс+окет",
        r"\bPython\s*3\.12\b": "П+айтон три точка двенадцать",
        r"\bPython\b": "П+айтон",
        r"\bWindows\s*11\b": "В+индовс одиннадцать",
        r"\bWindows\b": "В+индовс",
        r"\bLinux\b": "Л+инукс",
        r"\bDocker\b": "Д+окер",
        r"\bPostgreSQL\b": "Постгре Эс Кью Эль",
        r"\bPostgres\b": "П+остгрес",
        r"\bONNX\s*Runtime\b": "ОННИКС Рант+айм",
        r"\bONNX\b": "ОННИКС",
        r"\bPyTorch\b": "Пайт+орч",
        r"\bGitHub\b": "Гитх+аб",
        r"\bAPI\b": "АП+И",
        r"\bGPU\b": "ГПУ",
        r"\bCPU\b": "ЦПУ",
        r"\bLLM\b": "Эль Эль +Эм",
        r"\bJSON\b": "Дж+ейсон",
        r"\bHTTP\b": "ХТТП",
        r"\bHTTPS\b": "ХТТПС",
        r"\bURL\b": "ЮРЭЛ",
        r"\bUI\b": "Ю+Ай",
        r"\bUX\b": "Ю+Икс",
        r"\bAI\b": "Эй+Ай",
        r"\bbackend\b": "бэк+енд",
        r"\bfrontend\b": "фронт+енд",
        r"\bframework\b": "фреймв+орк",
        r"\bIris\b": "+Ирис",
        r"\bNeuroAsist\b": "НейроАсс+ист",
        r"\bNode(?:\.js|JS)\b": "Н+ода",
        r"\bReact\b": "Ре+акт",
        r"\bTypeScript\b": "Тайпскр+ипт",
        r"\bJavaScript\b": "Джаваскр+ипт",
    }.items()
)


def normalize_unicode_for_model(text: str) -> str:
    """Map common editor punctuation/stress marks to Tera's vocabulary.

    TeraTTS uses ``+`` immediately before a stressed character.  User text
    often carries the same information as a combining acute accent (``а́``).
    Normalizing it here avoids a warning and, more importantly, preserves the
    explicitly requested stress instead of letting the model drop the mark.
    """
    decomposed = unicodedata.normalize("NFD", text)
    output: list[str] = []
    for character in decomposed:
        if character == "\u0301":
            if output and output[-1] != "+":
                output[-1] = "+" + output[-1]
            continue
        output.append(character)
    normalized = unicodedata.normalize("NFC", "".join(output))
    return normalized.translate(str.maketrans({"—": " - ", "–": " - ", "‑": "-"}))


def _day_words(day: int, case: str) -> str:
    table = {"genitive": _DAY_GENITIVE, "accusative": _DAY_ACCUSATIVE, "dative": _DAY_DATIVE}[case]
    return table.get(day, str(day))


def normalize_dates(text: str) -> str:
    def replace_preposition(match: re.Match[str]) -> str:
        prep, raw_day, month = match.groups()
        case = "accusative" if prep.lower() == "на" else "dative"
        return f"{prep} {_day_words(int(raw_day), case)} {month}"

    text = re.sub(rf"\b(на|к)\s+(\d{{1,2}})\s+{_MONTH_RE}\b", replace_preposition, text, flags=re.IGNORECASE)
    text = re.sub(
        rf"\b(\d{{1,2}})\s+{_MONTH_RE}\b",
        lambda match: f"{_day_words(int(match.group(1)), 'genitive')} {match.group(2)}",
        text,
        flags=re.IGNORECASE,
    )

    def replace_year_preposition(match: re.Match[str]) -> str:
        prep, year, noun = match.groups()
        if year == "2026":
            return f"{prep} две тысячи двадцать шестом {noun}"
        return match.group(0)

    text = re.sub(r"\b(в|во)\s+(20\d{2})\s+(год(?:у|е))\b", replace_year_preposition, text, flags=re.IGNORECASE)
    genitive_years = {
        2020: "две тысячи двадцатого", 2021: "две тысячи двадцать первого",
        2022: "две тысячи двадцать второго", 2023: "две тысячи двадцать третьего",
        2024: "две тысячи двадцать четвёртого", 2025: "две тысячи двадцать пятого",
        2026: "две тысячи двадцать шестого", 2027: "две тысячи двадцать седьмого",
        2028: "две тысячи двадцать восьмого", 2029: "две тысячи двадцать девятого",
        2030: "две тысячи тридцатого",
    }
    text = re.sub(
        r"\b(20\d{2})\s+(года|год|лет)\b",
        lambda match: f"{genitive_years.get(int(match.group(1)), match.group(1))} {match.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    return text


def normalize_time(text: str) -> str:
    def replace_time(match: re.Match[str]) -> str:
        hour, minute = int(match.group(1)), int(match.group(2))
        return f"{hour} часов ровно" if minute == 0 else f"{hour} часов {minute} минут"

    return re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", replace_time, text)


def normalize_versions(text: str) -> str:
    def words(raw: str) -> str:
        return " точка ".join(_VERSION_DIGITS.get(part, part) for part in raw.split("."))

    text = re.sub(r"\b[vV](\d+(?:\.\d+)+)\b", lambda m: f"версия {words(m.group(1))}", text)
    text = re.sub(r"\b(\d+\.\d+(?:\.\d+)+)\b", lambda m: words(m.group(1)), text)
    return re.sub(r"\b[vV](\d+)\b", lambda m: f"версия {_VERSION_DIGITS.get(m.group(1), m.group(1))}", text)


def normalize_tech_terms(text: str) -> str:
    for pattern, replacement in _TECH_LEXICON:
        text = pattern.sub(replacement, text)
    return text


def normalize_for_teratts(text: str, pronunciations: dict[str, str] | None = None) -> str:
    """Return exactly one balanced Russian TeraTTSv2 span."""
    clean = re.sub(r"</?(?:ru|en)\b[^>]*>", "", str(text or ""), flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", "", clean)
    clean = normalize_unicode_for_model(clean)
    clean = normalize_dates(clean)
    clean = normalize_time(clean)
    clean = normalize_versions(clean)
    clean = normalize_tech_terms(clean)
    for source, replacement in (pronunciations or {}).items():
        if source.strip():
            clean = re.sub(re.escape(source), replacement, clean, flags=re.IGNORECASE)
    clean = " ".join(clean.split()).strip()
    if not clean:
        raise ValueError("TTS text is empty after normalization")
    return f"<ru>{clean}</ru>"
