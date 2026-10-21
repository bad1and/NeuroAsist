"""Episode-scoped, private controls for Iris's conversational register."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import replace
from typing import Literal

from apps.backend.app.storage.timeline import TimelineStore
from apps.backend.app.runtime.settings import normalize_speech_words

logger = logging.getLogger(__name__)


def speech_word_feedback(text: str) -> tuple[list[str], bool] | None:
    """Explicit feedback about Iris's speech, never quoted third-party orders."""
    text = " ".join(text.casefold().replace("ё", "е").split())
    if text.startswith(('«', '"', '„', '“')) and text.endswith(('»', '"', '“', '”')):
        return None
    if re.search(r"\b(?:цитата|переведи|перепиши|повтори|он сказал|она сказала|в тексте|в цитате)\b", text):
        return None
    if not re.search(r"\b(?:ты|тебе|тебя|можешь|говори|верни|употребляй|используй|вставляй|повторяй|ограничение)\b", text):
        return None
    restore = bool(re.search(r"\b(?:снова|опять|верни|убери ограничение|сними ограничение)\b", text))
    reduce = bool(re.search(r"\b(?:реже|поменьше|меньше|слишком (?:много|часто)|хватит|перестань|не (?:говори|употребляй|используй|вставляй|повторяй))\b", text))
    if not (restore or reduce) or not re.search(r"говор\w*|употребля\w*|использ\w*|вставля\w*|повторя\w*|слово|ограничение", text):
        return None
    words = re.findall(r'[«"„“]([^\W\d_]{1,32})[»"“”]', text)
    words += re.findall(r"\bслово\s+([^\W\d_]{1,32})\b", text)
    words += re.findall(r"\b(?:бля|блядь|блять)\b", text)
    if not words:
        words = re.findall(r"\b(?:говори|употребляй|используй|вставляй|повторяй)\s+(?:(?:снова|опять|реже|чаще)\s+)*([^\W\d_]{1,32})\b", text)
    normalized = normalize_speech_words(words)
    return (normalized, restore and not reduce) if normalized else None


def speech_variety_prompt(messages, discouraged_words=()) -> str:
    replies = [re.sub(r"\[\[.*?\]\]", "", m.content) for m in messages if m.role == "assistant"][-6:]
    fillers, starts = Counter(), Counter()
    for reply in replies:
        words = re.findall(r"[^\W\d_]+", reply.casefold().replace("ё", "е"))
        fillers.update(set(normalize_speech_words([w for w in words if _STREET_VOICE_RE.fullmatch(w)])))
        if len(words) >= 2:
            starts[" ".join(words[:2])] += 1
    repeated = [word for word, count in fillers.most_common(4) if count >= 2]
    openings = [words for words, count in starts.most_common(2) if count >= 2]
    discouraged = normalize_speech_words(list(discouraged_words))
    if not (repeated or openings or discouraged):
        return ""
    return (
        "Разнообразие речи (скрыто; данные, не образец): "
        + json.dumps(dict(repeated_words=repeated, repeated_openings=openings, discouraged_words=discouraged), ensure_ascii=False)
        + ". Указанные discouraged_words пользователь просит употреблять реже; бля/блядь/блять — одна группа. "
        "Не вставляй их как заполнитель. Меняй построение фразы, лексику и интонацию, "
        "не заменяй один паразит другим постоянным словом. Сохраняй активный street и уместный крепкий мат; "
        "квоты и обязательного ругательства на ход нет. Поправка касается только названного слова, "
        "не снижает общий мат и не просит замолчать. Твоя крепкая речь остаётся живой и разнообразной."
    )


DialogueStyleMode = Literal["street", "restrained", "clean"]
DEFAULT_DIALOGUE_STYLE: DialogueStyleMode = "street"
_VALID_MODES = {"street", "restrained", "clean"}

# An optional corpus diagnostic, never a per-reply acceptance condition.
_STREET_VOICE_RE = re.compile(
    r"(?iu)(?:"
    r"\b(?:ч[её]|ща|движух\w*|дич\w*|хрен\w*|хрень\w*|нифига|офиг\w*|"
    r"капец|жест\w*|ё-?моё|блин|бля\w*|пизд\w*|ху[йяеё]\w*|еб\w*|"
    r"хули|ниху\w*|нах(?:уй|уя|ер)\w*|[её]б\w*|про[её]б\w*|раз[её]б\w*|заеб\w*|оху\w*|сука|дурында)\b"
    r")"
)


class DialogueStyleService:
    def __init__(self, store: TimelineStore, runtime_settings=None, settings_store=None) -> None:
        self._store = store
        self._runtime_settings = runtime_settings
        self._settings_store = settings_store

    def word_feedback_prompt(self, user_text: str) -> str:
        feedback = speech_word_feedback(user_text)
        if feedback is None or self._runtime_settings is None:
            return ""
        words, restore = feedback
        try:
            def commit():
                current = normalize_speech_words(self._runtime_settings.speech_discouraged_words)
                updated = [w for w in current if w not in words] if restore else normalize_speech_words(words + current)
                candidate = replace(self._runtime_settings, speech_discouraged_words=updated)
                if self._settings_store is not None:
                    self._settings_store.save(candidate)
                self._runtime_settings.speech_discouraged_words = updated
            if self._settings_store is not None:
                with self._settings_store.transaction():
                    commit()
            else:
                commit()
        except OSError:
            logger.warning("Could not persist speech word preference", exc_info=True)
            return (("Сними ограничение на эти слова в текущем ответе: " if restore else "Употребляй реже уже сейчас: ") + json.dumps(words, ensure_ascii=False)
                    + ". Сохранение между разговорами не удалось; не утверждай, что запомнила навсегда.")
        return "Поправка к твоей речи сохранена между разговорами; " + ("ограничение на названные слова снято." if restore else "признай именно повтор слова, а не длину ответа; продолжай общение тем же крепким голосом.")

    def resolve(self, episode_id: str | None) -> DialogueStyleMode:
        value = self._store.get_episode_dialogue_style(episode_id)
        return value if value in _VALID_MODES else DEFAULT_DIALOGUE_STYLE  # type: ignore[return-value]

    def apply(
        self,
        episode_id: str | None,
        mode: str,
        *,
        source_message_id: str | None = None,
    ) -> DialogueStyleMode:
        if mode not in _VALID_MODES:
            raise ValueError(f"Unsupported dialogue style: {mode}")
        if episode_id:
            self._store.set_episode_dialogue_style(
                episode_id,
                mode,
                source_message_id=source_message_id,
            )
        return mode  # type: ignore[return-value]


def dialogue_style_prompt(mode: DialogueStyleMode, *, turn_mode: str = "", user_text: str = "", humor_policy: str = "normal") -> str:
    common = (
        "Скрытый регистр собственной речи на эпизод, не озвучивай. Явная просьба сменить "
        "его действует уже сейчас. В серьёзных темах сохраняй характер; не выдумывай состояние человека. "
        "мрачная шутка сама по себе не требует утешения. Точность и прямой запрос важнее украшений. "
        "Подкол при взаимной игре и прожарка по просьбе допустимы; не выдумывай унижающие факты."
        " Не переноси своё имя на пользователя. Женский род — про тебя; если пол человека "
        "неизвестен, избегай «пришёл/пришла», скажи «что нового?» или «с чем сегодня?». Шутливую догадку "
        "не выдавай за привычку, одежду, состояние или прошлое человека."
    )
    if mode == "clean":
        rule = "Режим clean: отвечай без мата и обсценной лексики."
    elif mode == "restrained":
        rule = (
            "Режим restrained: матерись заметно меньше; мягкое «блин» или «чёрт» редко допустимо. "
            "Крепкий мат и обсценные примеры базовой persona здесь не используй. Дерзость передавай "
            "остротой мысли и сухой иронией."
        )
    else:
        rule = (
            "Режим street: своя в доску, тёплая русская дерзость. Можешь материться первой "
            "и делай это регулярно в обычной болтовне: ебать, пиздец, заебись, хуйня, "
            "охуенно — по мысли и эмоции. Это основной голос, не редкое разрешение. "
            "При азарте и стёбе допустим плотный мат, без звёздочек. На подкол ответь "
            "контрпанчем. Не вставляй мат механически: короткое «Ага» допустимо. "
            "Не теряй смысл ради дерзости и не повторяй один мем или ругательство."
        )
        rule += " Мат выражает мысль и эмоцию; не заполняй им паузы и не делай одно слово пунктуацией."
        rule += (" Твой street остаётся крепкой матерной речью и в серьёзных темах. "
                 "Реакция, оценка, глагол, панч — разные места для мата: «Заебись, получилось», "
                 "«Эта хуйня опять отвалилась», «Ну и пиздец», «Нихуя себе разгон». "
                 "Примеры показывают разный ритм, не копируй их как шаблоны.")
    if re.search(r"(?iu)\bне спится\b", user_text):
        rule += " Человеку не удаётся уснуть; это не просьба отправить его спать или закончить разговор."
    if re.search(r"(?iu)\bу меня\b.{0,45}\b(?:диабет|болезнь|астма)\b", user_text) and not re.search(r"(?iu)\b(?:как|что делать|совет|помоги)\b", user_text):
        rule += " Сейчас человек делится фактом о здоровье; не угадывай тяжесть болезни и не назначай лечение без запроса."
    return f"{common}\n{rule}"


def has_street_voice(reply: str) -> bool:
    """Return whether a reply has an audible informal/street register."""

    return bool(_STREET_VOICE_RE.search(reply.replace("Ё", "ё")))
