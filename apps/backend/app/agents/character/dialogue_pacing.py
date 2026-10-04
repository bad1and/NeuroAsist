"""Deterministic turn-level pacing for Iris replies.

The model still writes the reply.  This module only tells it how much of the
conversation to take over in the current turn, so casual chat does not receive
the same response budget as an explanation or an explicitly requested deep
analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from apps.backend.app.agents.character.turn_intent import analyze_dialogue_turn, recent_reply_cue


DialogueMode = Literal["micro", "conversational", "focused", "deep"]


_WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)?", re.UNICODE)
_DEEP_REQUEST_RE = re.compile(
    r"(?iu)\b(?:подробно|детально|разв[её]рнуто|по\s+шагам|пошагово|"
    r"проанализируй|сделай\s+разбор|сравни\s+варианты|исследуй)\b"
)
_CASUAL_QUESTION_RE = re.compile(
    r"(?iu)^\s*(?:(?:ну|а|и)\s+)?(?:как\s+(?:ты|дела|сама)|ты\s+как|ч[её]\s+как)\s*[?!.]*\s*$"
)
_SHORT_REACTION_RE = re.compile(
    r"(?iu)^\s*(?:(?:ну|а|и)\s+)?(?:ага|угу|да|неа|нет|ясно|понятно|ладно|ок(?:ей)?)\b"
)
_SHORT_SOCIAL_BEAT_RE = re.compile(
    r"(?iu)\b(?:привет(?:ик)?|здравствуй|здорово|спасибо|благодарю|"
    r"смешно|лол|хаха+|заебись|охуенно|жесть|пиздец)\b"
)
_MICRO_RE = re.compile(
    r"(?iu)^\s*(?:(?:ну|а|и|да)\s+){0,2}(?:"
    r"привет(?:ик)?|здравствуй|здорово|доброе\s+утро|добрый\s+(?:день|вечер)|"
    r"пока|давай|ок(?:ей)?|ладно|ясно|понятно|ага|угу|неа|точно|"
    r"спасибо|благодарю|заебись|охуенно|смешно|лол|хаха+|мда|жесть|пиздец"
    r")(?:\s+(?:тебе|тоже|тогда|прям|это|было|ладно|спасибо))*\s*[?!.]*\s*$"
)


@dataclass(frozen=True)
class DialoguePacing:
    """One compact response-shape decision for the current user turn."""

    mode: DialogueMode

    def prompt_block(self, *, input_mode: str, recent_messages=()) -> str:
        rules = {
            "micro": (
                "Дай одну естественную короткую реплику, обычно одно предложение и до 12 слов. "
                "Простое согласие тоже полноценный ответ: характер не требует мата или шутки в каждом ходе. "
                "Не добавляй второй абзац, объяснение, пересказ или дежурный вопрос."
            ),
            "conversational": (
                "Ответь как в обычной переписке: 1-3 коротких предложения, один абзац, одна главная мысль. "
                "Реагируй на самое живое или важное, а не пересказывай всю реплику. Вопрос допустим только "
                "если тебе правда интересно продолжение, а не для поддержания видимости диалога."
            ),
            "focused": (
                "Сначала прямо ответь на вопрос или просьбу. Для одного факта достаточно короткой фразы; "
                "для объяснения — обычно 2-5 предложений, до двух коротких абзацев. Сам факт вопроса "
                "не превращает ответ в лекцию. Не повторяй вывод "
                "другими словами и не приклеивай лишнее предложение после уже полного ответа."
            ),
            "deep": (
                "Пользователь явно просит подробный разбор: дай нужную глубину и структуру, но без повторов, "
                "ритуального вступления и искусственного растягивания."
            ),
        }[self.mode]
        voice_rule = (
            " Это расшифровка речи: слова-паразиты и самопоправки задают естественный ритм, а не список тем, "
            "на каждую из которых надо отдельно ответить."
            if input_mode == "voice"
            else ""
        )
        return (
            "Ритм текущего хода Iris (внутреннее правило, не упоминай его):\n"
            f"- режим: {self.mode}. {rules}\n"
            "- Не собирай шаблон «реакция + шутка + объяснение + вопрос». Выбери один основной ход, "
            "иногда два, и оставь собеседнику место ответить. Это ограничивает длину, а не характер."
            f"{voice_rule}"
            f"{recent_reply_cue(recent_messages)}"
        )


def infer_dialogue_pacing(user_text: str, recent_messages=()) -> DialoguePacing:
    """Choose reply granularity from the current turn, not from its raw length."""

    text = " ".join(user_text.strip().split())
    words = _WORD_RE.findall(text)
    if _DEEP_REQUEST_RE.search(text):
        return DialoguePacing("deep")
    if _CASUAL_QUESTION_RE.fullmatch(text):
        return DialoguePacing("micro")
    intent = analyze_dialogue_turn(user_text, recent_messages)
    if intent.kind in {"greeting", "reaction", "correction"}:
        return DialoguePacing("micro")
    if intent.kind == "request" or "?" in text:
        return DialoguePacing("focused")
    if len(words) <= 6 and _MICRO_RE.fullmatch(text):
        return DialoguePacing("micro")
    if len(words) <= 5 and _SHORT_REACTION_RE.search(text):
        return DialoguePacing("micro")
    if len(words) <= 6 and (_SHORT_SOCIAL_BEAT_RE.search(text) or text.casefold() in {"ну", "мда"}):
        return DialoguePacing("micro")
    return DialoguePacing("conversational")
