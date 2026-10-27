"""Separate the user's preferences and feedback from reciprocal banter."""
from __future__ import annotations

import re


def user_feedback(text: str) -> str:
    text = " ".join(text.casefold().replace("ё", "е").split())
    if re.match(r'^(?:[«"„“]|(?:он|она)\s+сказал|цитата\b|переведи\s*:)', text):
        return ""
    if re.search(r"\b(?:не\s+(?:подкалывай|стебись|шути)|хватит\s+(?:подкол\w*|подкал\w*|стеб\w*|шут\w*)|перестань\s+(?:подкалывать|стебаться))\b", text):
        return "stop"
    discomfort = bool(re.search(r"\b(?:я\s+обидел\w*|мне\s+(?:обидно|неприятно)|меня\s+это\s+задел\w*)\b", text))
    if discomfort and not re.search(r"\b(?:ахах\w*|хаха\w*|лол|шучу)\b", text):
        return "discomfort"
    if re.search(r"\b(?:прожарь|подколи|постеби|стебани)\b", text):
        return ""
    if re.search(r"\b(?:мо[йяё]\s+любим\w*|мне\s+(?:это\s+)?нравится|я\s+(?:это\s+)?люблю)\b", text):
        return "preference"
    return ""


def feedback_prompt(text: str) -> str:
    kind = user_feedback(text)
    if not kind:
        return ""
    if kind == "stop":
        return "Пользователь явно просит прекратить этот подкол. Прекрати именно его; регистр, мат и собственное мнение сохраняются."
    if kind == "discomfort":
        return (
            "Пользователь сообщает, что ему неприятно или он обиделся. Заметь реакцию; не оспаривай её и не защищай прошлый панч как принцип. "
            "Можешь резко не соглашаться и сохранить мнение, мат и характер; не обязана хвалить или извиняться. "
            "Не застревай на одной насмешке и споре о вкусе, продолжи разговор."
        )
    return (
        "Пользователь сообщает свой вкус или реакцию; это не автоматическое приглашение продолжать прожарку. "
        "Прими факт, что ему нравится. Можешь резко оценить вкус и не согласиться; не обязана хвалить или извиняться. "
        "Не застревай на одной насмешке, продолжи по текущей просьбе."
    )
