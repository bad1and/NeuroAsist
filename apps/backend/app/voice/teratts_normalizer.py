"""Russian text preparation for TeraTTSv2.

TeraTTSv2 requires balanced language tags.  The application deliberately sends
one Russian span for Iris instead of mixing ``<ru>`` and ``<en>`` fragments:
technical English is rendered through a small pronunciation lexicon, while
ordinary numbers are left for the model's native ``num2words`` expansion.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from num2words import num2words


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
_DAY_ACCUSATIVE.update({3: "третье", 23: "двадцать третье"})
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

_CARDINAL_GENITIVE = {
    "ноль": "нуля", "один": "одного", "одна": "одной", "два": "двух", "две": "двух",
    "три": "трёх", "четыре": "четырёх", "пять": "пяти", "шесть": "шести",
    "семь": "семи", "восемь": "восьми", "девять": "девяти", "десять": "десяти",
    "одиннадцать": "одиннадцати", "двенадцать": "двенадцати", "тринадцать": "тринадцати",
    "четырнадцать": "четырнадцати", "пятнадцать": "пятнадцати", "шестнадцать": "шестнадцати",
    "семнадцать": "семнадцати", "восемнадцать": "восемнадцати", "девятнадцать": "девятнадцати",
    "двадцать": "двадцати", "тридцать": "тридцати", "сорок": "сорока",
    "пятьдесят": "пятидесяти", "шестьдесят": "шестидесяти", "семьдесят": "семидесяти",
    "восемьдесят": "восьмидесяти", "девяносто": "девяноста", "сто": "ста",
    "двести": "двухсот", "триста": "трёхсот", "четыреста": "четырёхсот",
    "пятьсот": "пятисот", "шестьсот": "шестисот", "семьсот": "семисот",
    "восемьсот": "восьмисот", "девятьсот": "девятисот", "тысяча": "тысячи",
    "тысячи": "тысяч", "тысяч": "тысяч", "миллион": "миллиона", "миллиона": "миллионов",
    "миллионов": "миллионов", "миллиард": "миллиарда", "миллиарда": "миллиардов",
    "миллиардов": "миллиардов",
}

_FEMININE_CARDINAL_NOUNS = (
    "минута", "минуты", "секунда", "секунды", "неделя", "недели", "страница", "страницы",
    "глава", "главы", "версия", "версии", "попытка", "попытки", "тысяча", "тысячи",
)

_ORDINAL_NEUTER_NOUNS = ("место", "число", "окно", "поле", "задание", "упражнение")

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
    # Keep semantic dashes until ranges have been recognized.  A prose dash is
    # converted to a pause later, while a dash between numbers means "from/to".
    return normalized.replace("‑", "-").replace("\u00a0", " ")


def _cardinal(value: int, *, feminine: bool = False) -> str:
    return str(num2words(value, lang="ru", gender="feminine" if feminine else "masculine"))


def _cardinal_genitive(value: int) -> str:
    words = _cardinal(value)
    return " ".join(_CARDINAL_GENITIVE.get(word, word) for word in words.split())


def _ordinal(value: int, *, form: str = "masculine") -> str:
    words = str(num2words(value, lang="ru", to="ordinal")).split()
    if not words:
        return str(value)
    word = words[-1]
    irregular = {
        ("третий", "feminine"): "третья", ("третий", "neuter"): "третье",
        ("третий", "genitive"): "третьего", ("третий", "dative"): "третьему",
        ("третий", "prepositional"): "третьем", ("третий", "instrumental"): "третьим",
    }
    if (word, form) in irregular:
        words[-1] = irregular[(word, form)]
        return " ".join(words)
    stem, soft = (word[:-2], word.endswith("ий"))
    endings = {
        "masculine": "ий" if soft else word[-2:],
        "feminine": "яя" if soft else "ая",
        "neuter": "ее" if soft else "ое",
        "genitive": "его" if soft else "ого",
        "dative": "ему" if soft else "ому",
        "prepositional": "ем" if soft else "ом",
        "instrumental": "им" if soft else "ым",
    }
    words[-1] = stem + endings.get(form, word[-2:])
    return " ".join(words)


def _plural(value: int, one: str, few: str, many: str) -> str:
    last_two = abs(value) % 100
    if 11 <= last_two <= 14:
        return many
    last = abs(value) % 10
    return one if last == 1 else few if 2 <= last <= 4 else many


def _day_words(day: int, case: str) -> str:
    table = {"genitive": _DAY_GENITIVE, "accusative": _DAY_ACCUSATIVE, "dative": _DAY_DATIVE}[case]
    return table.get(day, str(day))


def normalize_dates(text: str) -> str:
    def date_words(day: int, month: int, year: int, fallback: str) -> str:
        if not 1 <= day <= 31 or not 1 <= month <= 12:
            return fallback
        return (
            f"{_day_words(day, 'genitive')} {_MONTHS[month - 1]} "
            f"{_ordinal(year, form='genitive')} года"
        )

    def replace_numeric_date(match: re.Match[str]) -> str:
        day, month, year = (int(value) for value in match.groups())
        return date_words(day, month, year, match.group(0))

    def replace_iso_date(match: re.Match[str]) -> str:
        year, month, day = (int(value) for value in match.groups())
        return date_words(day, month, year, match.group(0))

    text = re.sub(
        r"\b((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})\b",
        replace_iso_date,
        text,
    )
    text = re.sub(
        r"\b(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d{2})\b",
        replace_numeric_date,
        text,
    )

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

    return text


def normalize_years(text: str) -> str:
    """Speak calendar years as ordinals with the case implied by the phrase."""
    year = r"(?:1[0-9]{3}|2[0-9]{3})"

    def replace_range(match: re.Match[str]) -> str:
        start, end = int(match.group(1)), int(match.group(2))
        return f"с {_ordinal(start, form='genitive')} по {_ordinal(end)} год"

    text = re.sub(
        rf"\b(?:с\s+)?({year})\s*(?:[-–—]\s*|по\s+)({year})(?:\s+(?:годы|годах|год))?\b",
        replace_range,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\b(в|во)\s+({year})(?:[-\s](?:м|ом))?\s+году\b",
        lambda m: f"{m.group(1)} {_ordinal(int(m.group(2)), form='prepositional')} году",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\b(к)\s+({year})(?:[-\s](?:му|ому))?\s+году\b",
        lambda m: f"{m.group(1)} {_ordinal(int(m.group(2)), form='dative')} году",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\b(до|с|от)\s+({year})(?:[-\s](?:го|ого))?\s+года\b",
        lambda m: f"{m.group(1)} {_ordinal(int(m.group(2)), form='genitive')} года",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\b({year})(?:[-\s](?:й|ый))?\s+год\b",
        lambda m: f"{_ordinal(int(m.group(1)))} год",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\b({year})(?:[-\s](?:го|ого))?\s+года\b",
        lambda m: f"{_ordinal(int(m.group(1)), form='genitive')} года",
        text,
        flags=re.IGNORECASE,
    )
    return text


def normalize_time(text: str) -> str:
    def replace_time(match: re.Match[str]) -> str:
        hour, minute = int(match.group(1)), int(match.group(2))
        hour_words = _cardinal(hour)
        hours = _plural(hour, "час", "часа", "часов")
        if minute == 0:
            return f"{hour_words} {hours} ровно"
        minute_words = _cardinal(minute, feminine=True)
        minutes = _plural(minute, "минута", "минуты", "минут")
        return f"{hour_words} {hours} {minute_words} {minutes}"

    return re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", replace_time, text)


def normalize_versions(text: str) -> str:
    def words(raw: str) -> str:
        return " точка ".join(_VERSION_DIGITS.get(part, part) for part in raw.split("."))

    text = re.sub(
        r"\bверсии\s+[vV](\d+(?:\.\d+)+)\b",
        lambda m: f"версии {words(m.group(1))}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b[vV](\d+(?:\.\d+)+)\b", lambda m: f"версия {words(m.group(1))}", text)
    text = re.sub(r"\b(\d+\.\d+(?:\.\d+)+)\b", lambda m: words(m.group(1)), text)
    return re.sub(r"\b[vV](\d+)\b", lambda m: f"версия {_VERSION_DIGITS.get(m.group(1), m.group(1))}", text)


def normalize_numeric_ranges(text: str) -> str:
    """Turn dash ranges into explicit Russian ``от … до …`` constructions."""
    pattern = r"(?<![\w.])(?:(от|с)\s+)?(-?\d+)\s*[-–—]\s*(-?\d+)(?![\w.])"

    def replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        left, right = int(match.group(2)), int(match.group(3))
        start = prefix.lower() if prefix else "от"
        return f"{start} {_cardinal_genitive(left)} до {_cardinal_genitive(right)}"

    text = re.sub(pattern, replace, text, flags=re.IGNORECASE)
    return re.sub(
        r"\b(от|с)\s+(-?\d+)\s+до\s+(-?\d+)\b",
        lambda m: f"{m.group(1)} {_cardinal_genitive(int(m.group(2)))} до {_cardinal_genitive(int(m.group(3)))}",
        text,
        flags=re.IGNORECASE,
    )


def normalize_ordinals(text: str) -> str:
    suffix_forms = {
        "й": "masculine", "ый": "masculine", "ой": "masculine",
        "я": "feminine", "ая": "feminine", "е": "neuter", "ое": "neuter",
        "го": "genitive", "ого": "genitive", "му": "dative", "ому": "dative",
        "м": "prepositional", "ом": "prepositional", "ым": "instrumental",
    }

    def replace_suffix(match: re.Match[str]) -> str:
        return _ordinal(int(match.group(1)), form=suffix_forms[match.group(2).lower()])

    text = re.sub(
        r"\b(\d+)\s*-(ый|ой|ая|ое|ого|ому|ым|й|я|е|го|му|ом|м)\b",
        replace_suffix,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bна\s+(\d+)\s+месте\b",
        lambda m: f"на {_ordinal(int(m.group(1)), form='prepositional')} месте",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(с|из)\s+(\d+)\s+места\b",
        lambda m: f"{m.group(1)} {_ordinal(int(m.group(2)), form='genitive')} места",
        text,
        flags=re.IGNORECASE,
    )
    nouns = "|".join(_ORDINAL_NEUTER_NOUNS)
    return re.sub(
        rf"\b(\d+)\s+({nouns})(?=\b)",
        lambda m: f"{_ordinal(int(m.group(1)), form='neuter')} {m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )


def normalize_quantities(text: str) -> str:
    """Expand remaining decimals and integers after contextual rules ran."""
    def replace_decimal_percent(match: re.Match[str]) -> str:
        value = Decimal(match.group(1).replace(",", "."))
        return f"{num2words(value, lang='ru')} процента"

    text = re.sub(r"(?<![\w.])(\d+[,.]\d+)\s*%", replace_decimal_percent, text)
    text = re.sub(
        r"(?<![\w.])(\d+)\s*%",
        lambda m: f"{_cardinal(int(m.group(1)))} {_plural(int(m.group(1)), 'процент', 'процента', 'процентов')}",
        text,
    )
    text = re.sub(r"\s*%", " процентов", text)
    feminine_nouns = "|".join(_FEMININE_CARDINAL_NOUNS)
    text = re.sub(
        rf"(?<![\w.])(\d+)\s+({feminine_nouns})(?=\b)",
        lambda m: f"{_cardinal(int(m.group(1)), feminine=True)} {m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )

    def replace_decimal(match: re.Match[str]) -> str:
        raw = match.group(0).replace(",", ".")
        try:
            return str(num2words(Decimal(raw), lang="ru"))
        except (InvalidOperation, ValueError):
            return match.group(0)

    text = re.sub(r"(?<![\w.])-?\d+[,.]\d+(?![\w.])", replace_decimal, text)
    text = re.sub(
        r"(?<![\w.])-?\d+(?![\w.])",
        lambda m: _cardinal(int(m.group(0))),
        text,
    )
    return text


def normalize_punctuation(text: str) -> str:
    """Translate typography into pauses TeraTTS renders consistently."""
    text = re.sub(r"\.{2,}", "…", text)
    text = re.sub(r"…+", "…", text)
    text = re.sub(r"\s*[—–]\s*", "; ", text)
    text = re.sub(r"\s+-\s+", "; ", text)
    text = re.sub(r"\s*;\s*", "; ", text)
    text = re.sub(r"\s*:\s*", ": ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"([!?])[!?]+", r"\1", text)
    text = re.sub(r"\s+([,;:.!?…])", r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def normalize_math_symbols(text: str) -> str:
    substitutions = (
        (r"(?<=\d)\s*\+\s*(?=\d)", " плюс "),
        (r"(?<=\d)\s*[−-]\s*(?=\d+\s*=)", " минус "),
        (r"(?<=\d)\s*[×*]\s*(?=\d)", " умножить на "),
        (r"(?<=\d)\s*/\s*(?=\d)", " разделить на "),
        (r"(?<=\d)\s*=\s*(?=\d)", " равно "),
    )
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text)
    return text


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
    clean = normalize_years(clean)
    clean = normalize_time(clean)
    clean = normalize_versions(clean)
    clean = normalize_math_symbols(clean)
    clean = normalize_numeric_ranges(clean)
    clean = normalize_ordinals(clean)
    clean = normalize_tech_terms(clean)
    for source, replacement in (pronunciations or {}).items():
        if source.strip():
            clean = re.sub(re.escape(source), replacement, clean, flags=re.IGNORECASE)
    clean = normalize_quantities(clean)
    clean = normalize_punctuation(clean)
    if not clean:
        raise ValueError("TTS text is empty after normalization")
    return f"<ru>{clean}</ru>"
