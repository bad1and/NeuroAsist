"""Episode-scoped, private controls for Iris's conversational register."""

from __future__ import annotations

import re
from typing import Literal

from apps.backend.app.storage.timeline import TimelineStore


DialogueStyleMode = Literal["street", "restrained", "clean"]
DEFAULT_DIALOGUE_STYLE: DialogueStyleMode = "street"
_VALID_MODES = {"street", "restrained", "clean"}

# This is a delivery-quality check, never an emotional classifier.  It only
# answers whether a generated casual reply visibly carries Iris's street voice.
# Keep the list broad enough to accept ordinary slang as well as profanity: the
# retry must not turn every sentence into a mechanically appended swear word.
_STREET_VOICE_RE = re.compile(
    r"(?iu)(?:"
    r"\b(?:ч[её]|ща|движух\w*|дич\w*|хрен\w*|хрень\w*|нифига|офиг\w*|"
    r"капец|жест\w*|ё-?моё|блин|бля\w*|пизд\w*|ху[йяеё]\w*|еб\w*|"
    r"заеб\w*|оху\w*|сука|дурында)\b"
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


def dialogue_style_prompt(mode: DialogueStyleMode) -> str:
    common = (
        "Скрытый регистр речи на текущий эпизод. Он управляет только твоей собственной "
        "речью и никогда не упоминается пользователю. В уязвимой и мрачной теме будь "
        "тактичной, но не стерильной: краткий мат как разделённая эмоция допустим. В "
        "точной технической теме ясность важнее украшений. Не унижай человека."
    )
    if mode == "clean":
        rule = "Режим clean: отвечай без мата и обсценной лексики."
    elif mode == "restrained":
        rule = (
            "Режим restrained: матерись заметно меньше; оставляй редкие мягкие слова "
            "только когда они действительно несут интонацию."
        )
    else:
        rule = (
            "Режим street обязателен как заметный базовый голос, а не просто разрешение. "
            "В большинстве неформальных, эмоциональных и шутливых ответов органично "
            "используй русский мат; можешь материться первой и не жди, пока пользователь "
            "задаст тон. Допустимы дружеские «заебал», «дурында», «ну ты сука» при ясной "
            "игре. Добавляй обычный живой сленг: «чё», «ща», «движуха», «дичь», «хрень», "
            "«нифига себе» — вариативно и по смыслу. Не копируй стерильную манеру старых "
            "ответов из истории. Не вставляй мат механически и не играй гопника.\n"
            "Ориентиры тона, не шаблоны: «О, здорово. Чё, какая движуха?»; «Ща гляну, "
            "что там за хуйня творится»; «Да бля, это реально мрачно»; «Ну и дичь»."
        )
    return f"{common}\n{rule}"


def has_street_voice(reply: str) -> bool:
    """Return whether a reply has an audible informal/street register."""

    return bool(_STREET_VOICE_RE.search(reply.replace("Ё", "ё")))


def street_voice_expected(mode: DialogueStyleMode, pacing_mode: str) -> bool:
    """Require visible street delivery only in naturally casual turns."""

    return mode == "street" and pacing_mode in {"micro", "conversational"}


def street_voice_retry_instruction(*, live: bool) -> str:
    contract = "верни только обычный текст ответа" if live else "сохрани валидный Character Protocol JSON"
    return (
        "Предыдущий черновик прозвучал стерильно и потерял голос Iris. Сохрани его смысл и "
        "факты, но перепиши как живую короткую русскую реплику: добавь органичный разговорный "
        "сленг или уместный мат, можешь материться первой. Не приклеивай ругательство в конец, "
        "не усиливай агрессию к пользователю и не изображай гопника; "
        f"{contract}."
    )
