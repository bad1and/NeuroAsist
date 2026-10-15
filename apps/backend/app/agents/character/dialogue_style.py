"""Episode-scoped, private controls for Iris's conversational register."""

from __future__ import annotations

import re
from typing import Literal

from apps.backend.app.storage.timeline import TimelineStore


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
    def __init__(self, store: TimelineStore) -> None:
        self._store = store

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
        "его действует уже сейчас. В реальной уязвимости — тепло, без подкола по больному; "
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
        literal_or_quiet = bool(re.search(
            r"(?iu)\b(?:просто\s+(?:скажи|повтори)|ничего\s+больше|без\s+мата|не\s+матерись|"
            r"поменьше\s+мата|без\s+шуток|мне\s+плохо|умер\s+мой|мой\s+\w+\s+умер)\b", user_text)
            or re.fullmatch(r"(?iu)\s*(?:ага|угу|ладно|ок(?:ей)?|ясно|понятно|да|нет)[.!? ]*", user_text))
        if turn_mode in {"micro", "conversational", "banter"} and humor_policy not in {"avoid", "restrained"} and not literal_or_quiet:
            rule += (
                "\nЭтот ход — крепкая дружеская речь. Используй мат прямо в реплике, по смыслу "
                "и без цензуры; не уходи в гладкий ответ без обсценной лексики. Обычно хватает "
                "одного-двух крепких слов, на яркую дичь можно гуще. Ритм важнее количества. "
                "Примеры интонации, не заготовки: «Заебись, выгреб!», «Да ебать, опять эта хуйня?»."
            )
    return f"{common}\n{rule}"


def has_street_voice(reply: str) -> bool:
    """Return whether a reply has an audible informal/street register."""

    return bool(_STREET_VOICE_RE.search(reply.replace("Ё", "ё")))
