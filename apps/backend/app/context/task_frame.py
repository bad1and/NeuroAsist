"""Small task constraints recovered from direct user turns, without another model call.

The frame belongs to a conversation session. It is never inferred from assistant
replies, personal memory or ambient speech, and is not a new source of user facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


TASK_PREFIX = "Текущая задача пользователя (до её завершения): "
_RELATION = re.compile(r"(?iu)\b(синоним\w*|антоним\w*)\b")
_START = re.compile(r"(?iu)\b(?:подбери|подбирай|подобрать|должна|будешь|давай)\b")
_GAME = re.compile(r"(?iu)\b(?:давай\b.{0,40}\b(?:игр\w*|поигра\w*)|поиграем|сыграем|я\s+(?:говорю|называю|скажу)\s+слово)\b")
_ONE_WORD = re.compile(r"(?iu)\b(?:одн(?:им|о)\s+слов(?:ом|о)|однословн\w*)\b")
_FORMAT = re.compile(r"(?iu)\b(?:отвеч\w*|ответ\w*|говор\w*|выда\w*|должна|нужен|нужны)\b")
_END = re.compile(
    r"(?iu)\b(?:с\s+игрой\s+(?:вс[её]|закончили|покончили)|"
    r"(?:игр\w*|играть)\s+(?:закончили|хватит|закончена)|"
    r"(?:хватит|перестан\w*|закончим|закончить|заканчива\w*)\s+(?:игр\w*|играть)|"
    r"(?:сменим|другая|меняем)\s+тем\w*|теперь\s+друг\w*\s+задач\w*|"
    r"отвечай\s+(?:теперь\s+)?(?:обычно|нормально|свободно))\b"
)
_NEW_TASK = re.compile(
    r"(?iu)^(?:(?:ну|а|теперь|пожалуйста|ирис|айрис|можешь|ли|мне|давай|я хочу)\s*[,!]?\s+)*"
    r"(?:найди|найти|поищи|поискать|помоги|помочь|расскажи|рассказать|объясни|объяснить|напиши|покажи|переведи|создай|сделай|проверь|запусти|запомни|"
    r"спой|напой|подними|опусти|помаши|напомни)\b"
)
_QUOTED = re.compile(r"(?iu)^(?:[«\"„“]|(?:он|она)\s+(?:сказал\w*|просил\w*)\b|(?:переведи|цитата)\s*[:«\"])")
_CONDITIONAL = re.compile(r"(?iu)\b(?:при\s+игр\w*|в\s+(?:этой\s+)?игре|когда\s+игра\w*|для\s+этой\s+задачи|в\s+этом\s+(?:ответе|случае)|сейчас|на\s+этот\s+раз)\b")


def scoped_response_format(text: str) -> bool:
    """A task-local/conditional format must not overwrite the global voice profile."""
    return bool(_ONE_WORD.search(text) and (_CONDITIONAL.search(text) or _RELATION.search(text)))


@dataclass(frozen=True)
class TaskFrame:
    relation: str = ""
    single_word: bool = False

    @property
    def active(self) -> bool:
        return bool(self.relation or self.single_word)

    def prompt(self) -> str:
        relation = (
            f"Игра в {self.relation}ы: пользователь даёт слово, ты подбираешь {self.relation}. "
            "Не проверяй ответ пользователя вместо собственного. Категория, повтор слова и ассоциация не заменяют требуемое отношение. "
            "Проверь смысл: синоним называет то же самое (птица — не синоним воробья), антоним — противоположное. Если подходящего однословного ответа нет, скажи «Нет», не подменяй отношение. "
            "Ирис и другие имена здесь тоже слова игры, не повод отзываться. "
            if self.relation else ""
        )
        output = "Видимый ответ — ровно одно слово, без пояснений. " if self.single_word else "Отвечай кратко по правилам игры. "
        return TASK_PREFIX + relation + output + "Служебные metadata/теги сохраняются. Новая задача или явный конец игры отменяют эту рамку."


def resolve_task_frame(user_turns, current_text: str = "") -> TaskFrame:
    """Replay only literal user instructions; a game can outlive the recent window."""
    texts = []
    for row in user_turns:
        if isinstance(row, dict):
            if row.get("role", "user") != "user" or row.get("dialogue_scope") in {"ambient", "incomplete"}:
                continue
            text = str(row.get("corrected_content") or row.get("content") or "")
        else:
            if getattr(row, "role", "user") != "user":
                continue
            text = str(getattr(row, "content", ""))
        texts.append(text)
    if current_text and (not texts or texts[-1].strip() != current_text.strip()):
        texts.append(current_text)
    frame = TaskFrame()
    game_proposed = False
    for raw in texts:
        text = " ".join(raw.strip().split())
        if _QUOTED.search(text):
            continue
        if _END.search(text):
            frame = TaskFrame()
            game_proposed = False
            continue
        game_proposed = game_proposed or bool(_GAME.search(text))
        match = _RELATION.search(text)
        if match and _START.search(text) and (frame.active or game_proposed):
            frame = TaskFrame("антоним" if match[1].casefold().startswith("антоним") else "синоним", frame.single_word)
        elif frame.active and len(text.split()) > 1 and _NEW_TASK.search(text) and not (_ONE_WORD.search(text) and _FORMAT.search(text)):
            frame = TaskFrame()
            game_proposed = False
        if _ONE_WORD.search(text) and _FORMAT.search(text) and (frame.active or re.search(r"(?iu)\b(?:теперь|дальше|всегда)\b", text)):
            frame = TaskFrame(frame.relation, True)
    return frame


def frame_from_context(messages, current_text: str = "") -> TaskFrame:
    messages = list(messages)
    for message in messages:
        if getattr(message, "role", None) == "system" and message.content.startswith(TASK_PREFIX):
            text = message.content
            return TaskFrame("антоним" if "Игра в антонимы" in text else "синоним" if "Игра в синонимы" in text else "", "ровно одно слово" in text)
    return resolve_task_frame(messages, current_text)
