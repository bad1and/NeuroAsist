from __future__ import annotations

import re
from dataclasses import dataclass

from apps.backend.app.schemas.character import Emotion


_EMOTIONS = frozenset(item.value for item in Emotion)
_GESTURES = frozenset({
    "none", "auto", "talk", "talk_right", "talk_left",
    "greeting", "greeting_right", "greeting_left", "greeting_casual",
    "agreement", "disagreement", "question", "question_right", "question_left",
    "explanation", "explanation_right", "explanation_left",
    "thinking", "thinking_right", "thinking_left",
    "surprise", "frustration",
    "farewell", "farewell_right", "farewell_left", "farewell_casual",
    "shrug", "nod",
    "head_scratch", "clapping", "laughing", "thumbs_up", "facepalm", "pointing", "bow",
})
_HEADER_RE = re.compile(
    r"^\[\[avatar\s+emotion=(?P<emotion>[a-z_]+)\s+gesture=(?P<gesture>[a-z_]+)\s+intensity=(?P<intensity>0(?:\.\d+)?|1(?:\.0+)?)\s*\]\]",
    re.IGNORECASE,
)
_LEADING_DIRECTION_RE = re.compile(r"^\s*\((?P<direction>[^()\n]{1,160})\)\s*", re.DOTALL)


@dataclass(frozen=True)
class AvatarDirective:
    emotion: Emotion = Emotion.NEUTRAL
    gesture: str = "auto"
    intensity: float = 1.0


_ATTR_RE = re.compile(
    r'([a-zA-Z_]+)\s*[:=]\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s\],]+))'
)


def infer_animation_directive(user_text: str = "", assistant_text: str = "") -> AvatarDirective:
    """Infer a natural, expressive emotion and gesture when the model omits explicit tags."""
    text = (assistant_text or "").strip()
    u_text = (user_text or "").strip()
    lower = text.lower()
    u_lower = u_text.lower()

    # 1. User explicit action requests take highest priority over generic speech particles
    wave_user = ("помаши", "помахай", "помахать", "маши рукой", "махай рукой", "маши ручкой", "махай ручкой", "wave")
    if any(w in u_lower for w in wave_user):
        return AvatarDirective(Emotion.HAPPY, "greeting_right", 0.9)

    scratch_triggers = ("почеши голову", "почеши затылок", "почесать затылок", "почесать голову", "чешет голову", "чешет затылок", "почеши в затылке", "почесаться", "чешу затылок", "почесал затылок", "почесала затылок", "чешет в затылке")
    if any(w in u_lower for w in scratch_triggers):
        return AvatarDirective(Emotion.THINKING, "head_scratch", 0.85)

    clap_triggers = ("похлопай", "похлопай в ладоши", "аплодисменты", "поаплодируй", "браво", "хлопай в ладоши")
    if any(w in u_lower for w in clap_triggers):
        return AvatarDirective(Emotion.HAPPY, "clapping", 0.9)

    laugh_triggers = ("посмейся", "засмейся", "хихикни", "рассмейся", "похихикай", "посмеяться")
    if any(w in u_lower for w in laugh_triggers):
        return AvatarDirective(Emotion.HAPPY, "laughing", 0.9)

    thumbs_triggers = ("покажи класс", "палец вверх", "покажи палец вверх", "поставь лайк", "лайкни", "класс!")
    if any(w in u_lower for w in thumbs_triggers):
        return AvatarDirective(Emotion.PROUD, "thumbs_up", 0.85)

    facepalm_triggers = ("фейспалм", "рукалицо", "рука лицо", "приложи руку к лицу", "испанский стыд", "позор")
    if any(w in u_lower for w in facepalm_triggers):
        return AvatarDirective(Emotion.EMBARRASSED, "facepalm", 0.85)

    bow_triggers = ("поклонись", "поклон", "сделай поклон", "отвесь поклон")
    if any(w in u_lower for w in bow_triggers):
        return AvatarDirective(Emotion.NEUTRAL, "bow", 0.85)

    if any(w in u_lower for w in ("покажи пальцем", "укажи пальцем", "укажи")):
        return AvatarDirective(Emotion.NEUTRAL, "pointing", 0.85)

    # 2. Farewells
    if any(w in u_lower for w in ("попрощайся", "помаши на прощание", "скажи пока")):
        return AvatarDirective(Emotion.NEUTRAL, "farewell_right", 0.85)

    # 3. Facial morphs (wink, pouting, teasing)
    if any(w in u_lower for w in ("подмигни", "моргни", "мигни")):
        return AvatarDirective(Emotion.WINK, "none", 0.9)
    if any(w in u_lower for w in ("надуй губки", "надуй щёчки", "надуй щечки", "обидься", "подуйся")):
        return AvatarDirective(Emotion.POUTING, "none", 0.9)
    if any(w in u_lower for w in ("покажи язык", "высуни язык", "покажи язычок", "дразнись", "подурачься")):
        return AvatarDirective(Emotion.TEASING, "none", 0.95)

    # 4. Nod / Shrug / Disagreement commands
    if any(w in u_lower for w in ("кивни", "кивни головой", "кивнуть", "кивок")):
        return AvatarDirective(Emotion.HAPPY, "nod", 0.85)
    if any(w in u_lower for w in ("помотай головой", "покачай головой")):
        return AvatarDirective(Emotion.SKEPTICAL, "disagreement", 0.85)
    if any(w in u_lower for w in ("пожми плечами", "пожать плечами", "разведи руками", "развести руками")):
        return AvatarDirective(Emotion.CONFUSED, "shrug", 0.8)

    # 5. Emotional reactions
    if any(w in u_lower for w in ("удивись", "сделай удивлён", "сделай удивлен")):
        return AvatarDirective(Emotion.SURPRISED, "surprise", 0.85)
    if any(w in u_lower for w in ("подумай", "задумайся", "сделай задумчивый")):
        return AvatarDirective(Emotion.THINKING, "thinking_right", 0.85)
    if any(w in u_lower for w in ("рассердись", "разозлись", "поругайся")):
        return AvatarDirective(Emotion.ANGRY, "frustration", 0.85)
    if any(w in u_lower for w in ("улыбнись", "порадуйся", "сделай радост")):
        return AvatarDirective(Emotion.HAPPY, "greeting_casual", 0.85)
    if any(w in u_lower for w in ("зевни", "поспи", "усни", "покажи как ты спишь")):
        return AvatarDirective(Emotion.SLEEPY, "none", 0.85)

    # 6. Assistant text and conversational matching
    wave_reply = ("помаши", "помахай", "машу", "машет", "махает", "помахала", "помахал", "ручкой", "рукой")
    if any(w in lower[:60] for w in wave_reply) and any(v in lower[:60] for v in ("машу", "машет", "махает", "помахала", "помаши", "помахай")):
        return AvatarDirective(Emotion.HAPPY, "greeting_right", 0.9)
    if any(lower.startswith(w) or f" {w}" in lower[:40] for w in ("привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер", "хай", "hello", "hi", "hey")):
        return AvatarDirective(Emotion.HAPPY, "greeting_right", 0.85)
    if any(u_lower.startswith(w) for w in ("привет", "здравствуй", "хай", "hello", "hi")):
        return AvatarDirective(Emotion.HAPPY, "greeting_right", 0.85)

    if any(w in lower[:50] for w in ("пока", "до свидания", "до встречи", "спокойной ночи", "до скорого", "bye", "goodbye")):
        return AvatarDirective(Emotion.NEUTRAL, "farewell_right", 0.85)

    if any(w in lower[:50] for w in ("подмигива", "подмигнула", "подмигнул", "мигаю")):
        return AvatarDirective(Emotion.WINK, "none", 0.85)
    if any(w in lower[:50] for w in ("надула", "надулись", "щёчки", "щечки", "губки")):
        return AvatarDirective(Emotion.POUTING, "none", 0.85)
    if any(w in lower[:50] for w in ("бе-бе", "язык", "шучу", "пошутила", "ха-ха", "хи-хи")):
        return AvatarDirective(Emotion.TEASING, "none", 0.9)

    if any(w in lower[:50] for w in ("кива", "кивнула", "кивнул")):
        return AvatarDirective(Emotion.HAPPY, "nod", 0.85)
    if any(lower.startswith(w) for w in ("да,", "да!", "конечно", "согласна", "точно", "именно так", "верно", "абсолютно")):
        return AvatarDirective(Emotion.HAPPY, "nod", 0.8)
    if any(u_lower.startswith(w) for w in ("да,", "да!", "именно", "точно", "верно", "согласен", "согласна")):
        return AvatarDirective(Emotion.HAPPY, "nod", 0.8)

    if any(lower.startswith(w) for w in ("нет,", "нет!", "не согласна", "не думаю", "не так", "неверно", "нельзя")):
        return AvatarDirective(Emotion.SKEPTICAL, "disagreement", 0.8)
    if any(u_lower.startswith(w) for w in ("нет,", "нет!", "ты не", "не так", "не соглас")):
        return AvatarDirective(Emotion.SKEPTICAL, "disagreement", 0.8)

    if any(w in lower[:50] for w in ("пожима", "пожала плечами", "пожал плечами", "развожу руками")):
        return AvatarDirective(Emotion.CONFUSED, "shrug", 0.8)
    if any(lower.startswith(w) for w in ("не знаю", "сложно сказать", "пожалуй", "как знать", "может быть")):
        return AvatarDirective(Emotion.CONFUSED, "shrug", 0.7)

    if any(lower.startswith(w) or f" {w}" in lower[:30] for w in ("ого", "вау", "ничего себе", "невероятно", "вот это да")):
        return AvatarDirective(Emotion.SURPRISED, "surprise", 0.85)

    if any(w in lower[:50] for w in ("задумалась", "задумался")):
        return AvatarDirective(Emotion.THINKING, "thinking_right", 0.85)
    if any(lower.startswith(w) for w in ("хм", "дай подумать", "интересный вопрос", "секунду", "погоди", "так-так")):
        return AvatarDirective(Emotion.THINKING, "thinking_right", 0.8)

    if any(w in lower[:40] for w in ("да блин", "сколько можно", "бесит", "раздражает", "ужас", "надоело")):
        return AvatarDirective(Emotion.ANNOYED, "frustration", 0.8)

    if any(w in lower for w in (
        "почесать затылок", "почешу затылок", "чешу затылок", "почесала затылок", "чешет затылок",
        "почесать голову", "почешу голову", "чешу голову", "почесала голову", "почесать в затылке",
        "чешу в затылке", "почесываю",
    )):
        return AvatarDirective(Emotion.THINKING, "head_scratch", 0.85)
    if any(w in lower for w in (
        "похлопать в ладоши", "хлопать в ладоши", "похлопать", "хлопаю в ладоши", "похлопаю",
        "похлопала", "хлопаю", "поаплодировать", "поаплодирую", "аплодирую", "аплодисменты", "браво",
    )):
        return AvatarDirective(Emotion.HAPPY, "clapping", 0.9)
    if any(w in lower for w in (
        "посмеяться", "посмеюсь", "смеюсь", "посмеялась", "похихикать", "хихикаю", "похихикаю",
        "рассмеяться", "рассмешил", "рассмешила", "ха-ха", "ахаха", "хи-хи", "смешно",
    )):
        return AvatarDirective(Emotion.HAPPY, "laughing", 0.85)
    if any(w in lower for w in (
        "палец вверх", "пальцы вверх", "показать класс", "покажу класс", "ставлю лайк",
        "поставить лайк", "лайк!", "класс!", "супер!", "отличная работа!", "молодец!",
    )):
        return AvatarDirective(Emotion.PROUD, "thumbs_up", 0.85)
    if any(w in lower for w in (
        "фейспалм", "рукалицо", "рука лицо", "испанский стыд", "приложить руку к лицу",
        "рука к лицу", "стыдно", "ой всё", "рука-лицо",
    )):
        return AvatarDirective(Emotion.EMBARRASSED, "facepalm", 0.85)
    if any(w in lower for w in (
        "поклон", "поклониться", "поклонюсь", "поклонилась", "кланяюсь", "мой поклон",
        "отвесить поклон", "отвешу поклон", "реверанс",
    )):
        return AvatarDirective(Emotion.NEUTRAL, "bow", 0.85)
    if any(w in lower for w in (
        "указать пальцем", "показать пальцем", "указываю пальцем", "показываю пальцем",
        "указываю", "укажу", "покажу туда", "смотри туда", "вон там", "вот там",
    )):
        return AvatarDirective(Emotion.NEUTRAL, "pointing", 0.85)

    # Questions / Curiosity
    if any(lower.startswith(w) for w in ("кто ", "что ", "где ", "когда ", "как ", "почему ", "зачем ", "откуда ", "куда ", "правда ли ")) or (len(text) < 80 and text.endswith("?")):
        return AvatarDirective(Emotion.CURIOUS, "question_right", 0.75)
    if any(u_lower.startswith(w) for w in ("кто ", "что ", "где ", "когда ", "как ", "почему ", "зачем ", "откуда ", "куда ", "расскажи ", "объясни ")) or (len(u_text) < 120 and u_text.endswith("?")):
        return AvatarDirective(Emotion.THINKING, "question_right", 0.75)

    # Default speech: conversational gesture so the character speaks with life
    return AvatarDirective(Emotion.HAPPY, "talk_right", 0.7)


def parse_avatar_directive(tag_text: str, default_emotion: Emotion | None = None, default_gesture: str | None = None) -> AvatarDirective:
    """Parse [[avatar ...]], [avatar ...], [anim: ...], [gesture: ...] tags with quote stripping and shorthand support."""
    inner = tag_text.strip()
    # Strip double or single outer brackets
    if inner.startswith("[[") and inner.endswith("]]"):
        inner = inner[2:-2].strip()
    elif inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1].strip()

    # Strip prefixes
    for prefix in ("avatar:", "avatar", "anim:", "anim", "gesture:", "gesture", "emotion:", "emotion"):
        if inner.lower().startswith(prefix):
            inner = inner[len(prefix):].strip()
            break

    # Extract key=value or key:value attributes
    raw_attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(inner):
        key = m.group(1).lower()
        val = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        if val is not None:
            raw_attrs[key] = val.strip().strip("'\"")

    # If no attributes matched, check if inner itself is a gesture or emotion name
    clean_inner = inner.lower().strip().strip("'\"").replace("-", "_")
    if not raw_attrs and clean_inner:
        if clean_inner in _GESTURES:
            raw_attrs["gesture"] = clean_inner
        elif clean_inner in _EMOTIONS or clean_inner in ("tongue", "tongue_out"):
            raw_attrs["emotion"] = clean_inner

    raw_emotion = raw_attrs.get("emotion", "").lower().replace("-", "_").strip()
    raw_gesture = raw_attrs.get("gesture", "").lower().replace("-", "_").strip()
    raw_intensity = raw_attrs.get("intensity")

    # Coerce emotion
    if raw_emotion in ("tongue", "tongue_out"):
        emotion = Emotion.TEASING
    elif raw_emotion in ("wink_right", "wink"):
        emotion = Emotion.WINK
    elif raw_emotion == "wink_left":
        emotion = Emotion.WINK_LEFT
    elif raw_emotion in ("smile", "joy"):
        emotion = Emotion.HAPPY
    elif raw_emotion in _EMOTIONS:
        emotion = Emotion(raw_emotion)
    elif default_emotion is not None and not raw_emotion:
        emotion = default_emotion
    else:
        emotion = Emotion.NEUTRAL

    # Coerce gesture
    if raw_gesture in _GESTURES:
        gesture = raw_gesture
    elif default_gesture is not None and not raw_gesture:
        gesture = default_gesture
    elif raw_emotion and raw_emotion not in ("neutral", "relaxed", "sleepy", "pouting", "wink", "wink_left", "teasing"):
        # Auto-resolve gesture matching the emotion
        auto_map = {
            "happy": "greeting_casual",
            "excited": "greeting_right",
            "proud": "nod",
            "touched": "nod",
            "thinking": "thinking_right",
            "curious": "question_right",
            "concerned": "thinking_right",
            "skeptical": "disagreement",
            "surprised": "surprise",
            "shocked": "surprise",
            "sad": "shrug",
            "confused": "shrug",
            "embarrassed": "shrug",
            "smirk": "shrug",
            "angry": "frustration",
            "annoyed": "frustration",
            "playful": "greeting_casual",
        }
        gesture = auto_map.get(raw_emotion, "auto")
    else:
        gesture = "auto"

    try:
        intensity = float(raw_intensity) if raw_intensity is not None else 1.0
        intensity = max(0.0, min(1.0, intensity))
    except (ValueError, TypeError):
        intensity = 1.0

    return AvatarDirective(emotion=emotion, gesture=gesture, intensity=intensity)


def make_live_directive_expressive(directive: AvatarDirective, user_text: str) -> AvatarDirective:
    """Respect the neural LLM directive directly without artificial keyword overrides."""
    return directive


class LiveDirectiveParser:
    """Consumes only a leading avatar directive and never releases it as spoken text."""

    _MAX_PREFIX = 192

    def __init__(self, user_text: str = "") -> None:
        self._buffer = ""
        self._resolved = False
        self._user_text = user_text

    def feed(self, delta: str) -> tuple[AvatarDirective | None, list[str]]:
        if not delta:
            return None, []
        if self._resolved:
            return None, [delta]
        self._buffer += delta
        return self._resolve(final=False)

    def finish(self) -> tuple[AvatarDirective | None, list[str]]:
        if self._resolved:
            return None, []
        return self._resolve(final=True)

    def _resolve(self, *, final: bool) -> tuple[AvatarDirective | None, list[str]]:
        source = self._buffer
        stripped = source.lstrip()
        leading_space = source[: len(source) - len(stripped)]

        if stripped.startswith("[[") or stripped.startswith("["):
            is_double = stripped.startswith("[[")
            close_token = "]]" if is_double else "]"
            end = stripped.find(close_token, 2 if is_double else 1)
            if end >= 0:
                header = stripped[: end + len(close_token)]
                remainder = leading_space + stripped[end + len(close_token) :]
                self._resolved = True
                self._buffer = ""
                directive = parse_avatar_directive(header)
                if directive.gesture in ("auto", "talk", "talk_right"):
                    inferred = infer_animation_directive(self._user_text, remainder)
                    if inferred.gesture not in ("auto", "talk", "talk_right"):
                        directive = AvatarDirective(
                            emotion=inferred.emotion if directive.emotion == Emotion.NEUTRAL else directive.emotion,
                            gesture=inferred.gesture,
                            intensity=inferred.intensity,
                        )
                    elif directive.gesture == "auto" and directive.emotion == Emotion.NEUTRAL:
                        directive = inferred
                return directive, self._parts(remainder)
            if not final and len(stripped) <= self._MAX_PREFIX:
                return None, []
            self._resolved = True
            self._buffer = ""
            # A malformed machine header is never user-facing speech.
            inferred = infer_animation_directive(self._user_text, source)
            return inferred, []

        if stripped.startswith("("):
            match = _LEADING_DIRECTION_RE.match(source)
            if match is not None:
                self._resolved = True
                self._buffer = ""
                return self._from_legacy_direction(match.group("direction")), self._parts(source[match.end() :])
            if not final and len(stripped) <= self._MAX_PREFIX:
                return None, []

        self._resolved = True
        self._buffer = ""
        inferred = infer_animation_directive(self._user_text, source)
        return inferred, self._parts(source)

    @staticmethod
    def _parts(value: str) -> list[str]:
        return [value] if value.strip() else []

    @staticmethod
    def _from_header(match: re.Match[str] | None) -> AvatarDirective:
        if match is None:
            return AvatarDirective()
        return parse_avatar_directive(match.group(0))

    @staticmethod
    def _from_legacy_direction(value: str) -> AvatarDirective:
        text = value.lower()
        if any(word in text for word in ("саркаст", "ухмыл", "усмеш")):
            return AvatarDirective(Emotion.SMIRK, "shrug", 0.55)
        if "кива" in text:
            return AvatarDirective(Emotion.HAPPY, "agreement", 0.7)
        if any(word in text for word in ("удив", "изум")):
            return AvatarDirective(Emotion.SURPRISED, "surprise", 0.8)
        if any(word in text for word in ("раздраж", "злоб", "серд")):
            return AvatarDirective(Emotion.ANNOYED, "frustration", 0.65)
        if any(word in text for word in ("груст", "печал")):
            return AvatarDirective(Emotion.SAD, "shrug", 0.65)
        if any(word in text for word in ("задум", "размыш")):
            return AvatarDirective(Emotion.THINKING, "thinking_right", 0.55)
        if any(word in text for word in ("улыб", "радост")):
            return AvatarDirective(Emotion.HAPPY, "talk_right", 0.7)
        return AvatarDirective(Emotion.HAPPY, "talk_right", 0.6)


def clean_live_reply(raw_reply: str) -> str:
    """Strip the initial control/directorial prefix before committing the reply to history."""
    from apps.backend.app.voice.delivery import clean_voice_directives
    parser = LiveDirectiveParser()
    _, parts = parser.feed(raw_reply)
    _, tail = parser.finish()
    cleaned = clean_voice_directives("".join([*parts, *tail]))
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" ([.,!?:;…])", r"\1", cleaned)
    return cleaned.strip()
