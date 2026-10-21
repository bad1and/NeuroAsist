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


DialogueMode = Literal["micro", "conversational", "banter", "focused", "deep"]


_WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)?", re.UNICODE)
_DEEP_REQUEST_RE = re.compile(
    r"(?iu)\b(?:подробно|детально|разв[её]рнуто|по\s+шагам|пошагово|"
    r"проанализируй|сделай\s+разбор|сравни\s+варианты|исследуй)\b"
)
_CASUAL_QUESTION_RE = re.compile(
    r"(?iu)^\s*(?:(?:ну|а|и)\s+)?(?:как\s+(?:ты|дела|сама)|ты\s+как|ч[её]\s+как)\s*[?!.]*\s*$"
)
# Only an explicit entertainment request changes pacing. Mentions, quotations,
# real distress and questions about the meaning of a meme keep their own intent.
_BANTER_REQUEST_RE = re.compile(
    r"(?iu)^\s*(?:(?:ну|а|давай|ирис|айрис|пожалуйста)\s*[,!]?\s+)*"
    r"(?:(?:можешь|можешь\s+ты)\s+)?(?:"
    r"(?:прожарь|подъеби|подколи|стебани|постеби|пошути|шуткани|шуткан[иь]|пошутить|прожарить)\b|"
    r"(?:расскажи|рассказать|придумай|придумать|выдай|скажи)\s+(?:(?:мне|ещ[её]|какую-нибудь|смешную|смешной|тупую|тупой)\s+)*"
    r"(?:шутку|анекдот\w*)\b)"
)
_HUMOR_FOLLOWUP_RE = re.compile(r"(?iu)(?:\b(?:давай|расскажи|дай)\b.{0,55}\b(?:ещ[её]|друг\w*)\b|\b(?:ещ[её]|друг\w*)\b.{0,20}\bрасскажи\b|\bанекдот\w*\b)")
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
    turn_kind: str = ""

    def prompt_block(self, *, input_mode: str, recent_messages=(), user_text: str = "") -> str:
        recent_messages = list(recent_messages)
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
            "banter": (
                "Пользователь просит шутку или прожарку: дай сетап и панч либо один острый ответ, "
                "обычно 1-3 предложения. Не объясняй, почему это смешно, не начинай с объявления "
                "У развязки должна быть понятная связь с сетапом; случайная нелепость и мат не заменяют панч. "
                "режима и не добавляй совет после панча. Регистр clean/restrained и эмоциональные "
                "границы сохраняются; просьба разрешает игру, а не выдумывание фактов."
            ),
            "focused": (
                "Сначала прямо ответь на вопрос или просьбу. Для одного факта достаточно короткой фразы; "
                "для объяснения — обычно 2-5 предложений, до двух коротких абзацев. Сам факт вопроса "
                "не превращает ответ в лекцию. Не повторяй вывод "
                "другими словами или второй аналогией; сравнение — только если помогает понять."
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
        repair_rule = ""
        nearby_users = [m.content for m in recent_messages if getattr(m, "role", None) == "user"][-4:]
        if any(_BANTER_REQUEST_RE.search(text) or re.search(r"(?iu)\bанекдот\w*\b", text) for text in nearby_users):
            repair_rule = (
                "\nЕсли спрашивают, в чём смысл твоей шутки, проверь связку сетапа с развязкой. "
                "Не придумывай отсутствующую причину и не выдавай догадку за объяснение. "
                "Если связь потеряна — прямо скажи, что испортила анекдот. Например, из «сидел "
                "в автобусе, потом заболела нога» причина боли не следует; это не панч. "
                "На вопрос о смысле ответь по сути; новый анекдот — лишь по просьбе. "
                "Когда просят замену, меняй сюжет, не латая отсутствующую причину случайной деталью. "
                "При критике не оправдывай неудачную шутку и не защищай свою роль."
            )
            if len(user_text.split()) <= 8 and re.search(r"(?iu)\b(?:там|это|а ч[её] так|почему)\b", user_text) and not re.search(r"(?iu)\b(?:кстати|серь[её]зно|новост\w*|поищи)\b", user_text):
                repair_rule += " Короткое уточнение сейчас относится к последней шутке; не возобновляй старую новость по слову из реплики."
        intent_rule = (
            "\nЭто приветствие, не жалоба: «здорово, заебал» и STT «здорово заебало» — дружеская "
            "формула. Поздоровайся; не спрашивай, что заебало."
        ) if self.turn_kind == "greeting" else ""
        if self.turn_kind == "address":
            intent_rule = "\nЭто обращение к Iris, включая ошибку распознавания имени. Коротко отзовись; не сочиняй происхождение имени."
        return (
            "Ритм Iris (скрыто):\n"
            f"- режим: {self.mode}. {rules}\n"
            "- Без шаблона «реакция + шутка + объяснение + вопрос». Это ограничивает длину, а не характер."
            f"{voice_rule}"
            f"{repair_rule}"
            f"{intent_rule}"
            f"{recent_reply_cue(recent_messages)}"
        )


def infer_dialogue_pacing(user_text: str, recent_messages=()) -> DialoguePacing:
    """Choose reply granularity from the current turn, not from its raw length."""

    text = " ".join(user_text.strip().split())
    words = _WORD_RE.findall(text)
    if text.casefold().strip(" ,.!?") in {"ирис", "айрис", "ириска", "люрис"}:
        return DialoguePacing("micro", turn_kind="address")
    if _DEEP_REQUEST_RE.search(text):
        return DialoguePacing("deep")
    if _BANTER_REQUEST_RE.search(text):
        return DialoguePacing("banter")
    if _HUMOR_FOLLOWUP_RE.search(text) and not re.search(
        r"(?iu)\b(?:не\s+шути|хватит|серь[её]зно|объясни|суть|смысл|почему|откуда|"
        r"в\s+ч[её]м|как\s+это|не\s+пон[яи]\w*|не\s+понят\w*)\b", text
    ):
        nearby_users = [m.content for m in recent_messages if getattr(m, "role", None) == "user"][-3:]
        explicit_anecdote = bool(re.search(r"(?iu)\bанекдот\w*\b", text)
                                 and re.match(r"(?iu)^\s*(?:(?:не|ну|а)\s+)*(?:давай|дай|расскажи)\b", text))
        if explicit_anecdote or any(_BANTER_REQUEST_RE.search(previous) or re.search(r"(?iu)\bанекдот\w*\b", previous) for previous in nearby_users):
            return DialoguePacing("banter")
    if _CASUAL_QUESTION_RE.fullmatch(text):
        return DialoguePacing("micro")
    intent = analyze_dialogue_turn(user_text, recent_messages)
    if intent.kind == "greeting":
        return DialoguePacing("micro", turn_kind="greeting")
    if intent.kind in {"reaction", "correction"}:
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
