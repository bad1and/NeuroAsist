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
            "Режим street: живой дерзкий разговорный голос. Можешь материться первой, "
            "использовать сленг и дружеские подколы при ясной игре. Не вставляй мат "
            "механически и не играй гопника. Мат, шутка и сленг необязательны в отдельной "
            "реплике: простое «Ага» тоже естественно. Регистр сохраняется на протяжении "
            "диалога, а не проверяется по каждому слову."
        )
    return f"{common}\n{rule}"


def has_street_voice(reply: str) -> bool:
    """Return whether a reply has an audible informal/street register."""

    return bool(_STREET_VOICE_RE.search(reply.replace("Ё", "ё")))
