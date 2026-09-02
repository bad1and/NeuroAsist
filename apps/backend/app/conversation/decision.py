from __future__ import annotations

import re
from dataclasses import dataclass

from apps.backend.app.conversation.schemas import (
    ConversationAction,
    ConversationDecision,
    DecisionReason,
    EventAppraisal,
    SpeakerRole,
)
from apps.backend.app.conversation.state import AffectState, CharacterStateReducer


@dataclass(frozen=True)
class DecisionContext:
    turn_complete: bool = True
    speaker_role: SpeakerRole = SpeakerRole.PRIMARY
    speaker_confidence: float = 0.9
    addressedness: float | None = None
    relevance: float = 0.5
    significance: float = 0.2
    social_permission: float = 0.5
    novelty: float = 0.5
    turn_confidence: float = 1.0
    cooldown_active: bool = False
    speech_budget_exceeded: bool = False
    initiative: bool = False
    engagement: str = "balanced"
    implicit_address: bool = False
    addressed_to_other: bool = False


@dataclass(frozen=True)
class AddressingAnalysis:
    """Deterministic addressing evidence shared by decision and context repair."""

    kind: str
    direct_iris: bool
    implicit_iris: bool
    other_person: bool
    reasons: tuple[str, ...] = ()


class ConversationDecisionEngine:
    """Hard gates plus deterministic engagement scoring.

    Ambiguous cases may later be enriched by a structured LLM adjudicator; the
    reducer remains the authority and always has a conservative local fallback.
    """

    _name = re.compile(
        r"(?iu)(?:^|[\s,!.?—-])(?:iris|айрис|ирис|ириска|ириск|ирес|иреск)(?:$|[\s,!.?—-])"
    )
    _invitation = re.compile(
        r"(?iu)\b(?:что думаешь|как считаешь|тво[её] мнение|скажи|ответь|прокомментируй|а ты)\b"
    )
    _implicit_request = re.compile(
        r"(?iu)(?:"
        r"\b(?:можешь|могла\s+бы|подскажи|расскажи|объясни|покажи|скинь|пришли|"
        r"дай|помоги|посоветуй|найди|открой|включи|выключи)\b|"
        r"^\s*(?:(?:а|ну|кстати|слушай|смотри|короче)\s+){0,3}"
        r"(?:что|кто|где|куда|откуда|когда|почему|зачем|как|"
        r"какой|какая|какое|какие|какую|какою|какого|какому|каким|каком|"
        r"каких|какими|который|которая|которое|которые|которую|которого|"
        r"которому|которым|котором|которых|которыми|сколько|чем)(?=\s|[?？])"
        r")"
    )
    _interrogative_opening = re.compile(
        r"(?iu)^\s*(?:(?:а|ну|кстати|слушай|смотри|короче)\s+){0,3}"
        r"(?:что|кто|где|куда|откуда|когда|почему|зачем|как|"
        r"какой|какая|какое|какие|какую|какою|какого|какому|каким|каком|"
        r"каких|какими|который|которая|которое|которые|которую|которого|"
        r"которому|которым|котором|которых|которыми|сколько|чем)(?=\s|[?？])"
    )
    _self_talk = re.compile(r"(?iu)\b(?:думаю вслух|сам с собой|не обращай внимания)\b")
    _question = re.compile(r"[?？]\s*$")
    _known_other_name = re.compile(
        r"(?iu)^\s*(?:(?:а|ну|так|эй|слушай)\s+){0,2}(?:"
        r"олег|рома|роман|лука|федя|фёдор|федор|саша|александр|алексей|лёша|леша|"
        r"дима|дмитрий|сергей|андрей|антон|макс|максим|миша|михаил|никита|"
        r"ваня|иван|паша|павел|катя|екатерина|маша|мария|даша|дарья|настя|"
        r"анастасия|лена|елена|оля|ольга|аня|анна|лиза|елизавета|юля|юлия"
        r")(?:\s|,|$)"
    )
    _generic_other_vocative = re.compile(
        r"(?iu)^\s*(?:(?:а|ну|так|эй|слушай)\s+){0,2}"
        r"(?P<name>[а-яёa-z]{2,20})(?P<separator>,\s*|\s+)"
        r"(?P<tail>.+)$"
    )
    _generic_other_command = re.compile(
        r"(?iu)^(?:"
        r"(?:ты|вы)\s+(?:можешь|можете|зайди|зайдите|подойди|подойдите|"
        r"включи|включите|выключи|выключите|скажи|скажите|посмотри|"
        r"посмотрите|давай|давайте)\b|"
        r"(?:можешь|можете|зайди|зайдите|подойди|подойдите|включи|"
        r"включите|выключи|выключите|скажи|скажите|посмотри|посмотрите|"
        r"давай|давайте|привет|пока)\b"
        r")"
    )
    _non_names = {
        "iris", "айрис", "ирис", "ириска", "ириск", "ирес", "иреск",
        "а", "ну", "так", "да", "нет", "блин", "слушай", "смотри", "кстати",
        "короче", "что", "кто", "где", "куда", "откуда", "когда", "почему",
        "зачем", "как", "какой", "какая", "какое", "какие", "какую", "какою",
        "какого", "какому", "каким", "каком", "каких", "какими", "который",
        "которая", "которое", "которые", "которую", "которого", "которому",
        "которым", "котором", "которых", "которыми", "сколько", "чем",
    }

    def decide(
        self,
        transcript: str,
        context: DecisionContext,
        *,
        affect: AffectState | None = None,
        assistant_echo: bool = False,
    ) -> ConversationDecision:
        addressedness = context.addressedness
        if addressedness is None:
            addressedness = self.addressedness(transcript)
        significance = context.significance
        reaction = CharacterStateReducer.display_emotion(affect or AffectState())

        if assistant_echo or context.speaker_role is SpeakerRole.ASSISTANT_ECHO:
            return self._decision(ConversationAction.OBSERVE, DecisionReason.ECHO, 1.0, 0.0, 0.0, 0.0)
        if not context.turn_complete:
            return self._decision(
                ConversationAction.WAIT_MORE,
                DecisionReason.INCOMPLETE_TURN,
                context.turn_confidence,
                addressedness,
                context.relevance,
                significance,
                reaction,
            )
        if context.addressed_to_other:
            return self._decision(
                ConversationAction.OBSERVE,
                DecisionReason.OTHER_PERSON,
                0.95,
                0.0,
                context.relevance,
                significance,
                reaction,
            )
        invited = bool(self._invitation.search(transcript)) or context.implicit_address
        direct = addressedness >= 0.86 or (invited and addressedness >= 0.55)
        if direct:
            return self._decision(
                ConversationAction.RESPOND,
                DecisionReason.DIRECT_ADDRESS if addressedness >= 0.86 else DecisionReason.INVITED,
                max(0.9, addressedness),
                addressedness,
                context.relevance,
                significance,
                reaction,
            )
        if context.speaker_role in {SpeakerRole.OTHER, SpeakerRole.UNKNOWN} and context.speaker_confidence >= 0.65:
            return self._decision(
                ConversationAction.OBSERVE,
                DecisionReason.OTHER_PERSON,
                context.speaker_confidence,
                addressedness,
                context.relevance,
                significance,
                reaction,
            )
        if self._self_talk.search(transcript):
            if significance >= 0.65 and context.speaker_role is SpeakerRole.PRIMARY:
                decision = self._decision(
                    ConversationAction.DEFER,
                    DecisionReason.EMOTIONAL_EVENT,
                    0.72,
                    addressedness,
                    context.relevance,
                    significance,
                    reaction,
                )
                return decision.model_copy(
                    update={"defer_for_ms": 1500, "expires_in_ms": 45_000}
                )
            return self._decision(
                ConversationAction.OBSERVE,
                DecisionReason.SELF_TALK,
                0.9,
                addressedness,
                context.relevance,
                significance,
                reaction,
            )
        if context.initiative and context.cooldown_active:
            return self._decision(
                ConversationAction.OBSERVE, DecisionReason.COOLDOWN, 0.95, addressedness, context.relevance, significance
            )
        if context.initiative and context.speech_budget_exceeded:
            return self._decision(
                ConversationAction.OBSERVE,
                DecisionReason.SPEECH_BUDGET,
                0.95,
                addressedness,
                context.relevance,
                significance,
            )

        if (
            significance >= 0.7
            and addressedness < 0.48
            and context.speaker_role is SpeakerRole.PRIMARY
        ):
            decision = self._decision(
                ConversationAction.DEFER,
                DecisionReason.EMOTIONAL_EVENT,
                0.72,
                addressedness,
                context.relevance,
                significance,
                reaction,
            )
            return decision.model_copy(
                update={"defer_for_ms": 1500, "expires_in_ms": 45_000}
            )

        score = (
            0.35 * addressedness
            + 0.20 * context.relevance
            + 0.15 * context.social_permission
            + 0.10 * ((affect.interest if affect else 0.5))
            + 0.10 * context.turn_confidence
            + 0.10 * context.novelty
        )
        score += {"low": -0.10, "balanced": 0.0, "high": 0.08}.get(context.engagement, 0.0)
        if context.initiative and score < 0.85:
            return self._decision(
                ConversationAction.OBSERVE,
                DecisionReason.AMBIENT_SPEECH,
                1.0 - score,
                addressedness,
                context.relevance,
                significance,
                reaction,
            )
        if score < 0.48:
            action = ConversationAction.OBSERVE
        elif score < 0.62:
            action = ConversationAction.AVATAR_REACTION
        elif score < 0.78:
            action = ConversationAction.BACKCHANNEL
        else:
            action = ConversationAction.RESPOND
        reason = DecisionReason.EMOTIONAL_EVENT if significance >= 0.65 else DecisionReason.RELEVANT_OPENING
        return self._decision(action, reason, min(1.0, max(score, 1.0 - abs(score - 0.63))), addressedness, context.relevance, significance, reaction)

    def addressedness(self, transcript: str) -> float:
        if self._name.search(transcript):
            return 1.0
        if self._invitation.search(transcript):
            return 0.72
        if self._question.search(transcript):
            return 0.42
        return 0.08

    def is_implicit_address(self, transcript: str) -> bool:
        """Detect a normal one-to-one request even when STT omits punctuation."""
        return bool(self._implicit_request.search(transcript))

    def is_self_talk(self, transcript: str) -> bool:
        """Recognize an explicit request not to join the speaker's monologue."""
        return bool(self._self_talk.search(transcript))

    def is_addressed_to_other(self, transcript: str) -> bool:
        """Detect a vocative aimed at a nearby person rather than Iris."""
        text = transcript.strip()
        if self._known_other_name.search(text):
            return True
        match = self._generic_other_vocative.search(text)
        if match is None:
            return False
        candidate = match.group("name").casefold()
        if candidate in self._non_names:
            return False
        # Unknown names need stronger evidence than an arbitrary token followed
        # by "ты/вы".  STT often omits commas, so a command-shaped continuation
        # remains sufficient (for example, "Арсен ты можешь...").
        tail = match.group("tail").strip()
        comma_pronoun = bool(
            match.group("separator").lstrip().startswith(",")
            and re.match(r"(?iu)^(?:ты|вы)\b", tail)
        )
        return bool(comma_pronoun or self._generic_other_command.search(tail))

    def analyze_addressing(self, transcript: str) -> AddressingAnalysis:
        """Return one consistent addressing classification with audit reasons."""
        direct = bool(self._name.search(transcript))
        other = False if direct else self.is_addressed_to_other(transcript)
        implicit = False if direct or other else self.is_implicit_address(transcript)
        if direct:
            return AddressingAnalysis(
                "direct_iris", True, False, False, ("direct_iris",),
            )
        if other:
            return AddressingAnalysis(
                "other_person", False, False, True, ("other_vocative",),
            )
        if implicit:
            reason = (
                "interrogative_followup"
                if self._interrogative_opening.search(transcript)
                else "implicit_request"
            )
            return AddressingAnalysis(
                "implicit_iris", False, True, False, (reason,),
            )
        return AddressingAnalysis(
            "ambiguous", False, False, False, ("insufficient_addressing_evidence",),
        )

    @staticmethod
    def appraise(
        transcript: str,
        message_id: str,
        participant: str = "primary",
        previous_assistant_text: str | None = None,
    ) -> EventAppraisal:
        text = transcript.casefold()
        affection = bool(re.search(r"\b(?:я\s+)?тебя\s+люблю\b|\bлюблю\s+тебя\b|\bобнимаю\s+тебя\b", text))
        if affection:
            return EventAppraisal(
                event_kind="affection", confidence=.92,
                intensity=min(1.0, 0.45 + len(text) / 500), valence=.55, arousal=.55,
                direction="toward_iris", target_participant=participant,
                emotion_impulses={"joy": .35, "playfulness": .12},
                relationship_impulses={"warmth": .25}, cause_message_ids=[message_id],
            )
        correction = re.search(r"\bне\s+([\w.ё-]+)\s*,?\s+а\s+([\w.ё-]+)\b", text)
        if correction and previous_assistant_text:
            old_value = correction.group(1).strip(".").casefold()
            if old_value and old_value in previous_assistant_text.casefold():
                return EventAppraisal(
                    event_kind="iris_mistake_corrected", confidence=.93, intensity=.58,
                    valence=-.12, arousal=.35, direction="toward_iris",
                    target_participant=participant,
                    emotion_impulses={"embarrassment": .35, "interest": .18},
                    relationship_impulses={"tension": -.03}, cause_message_ids=[message_id],
                )
        mappings = (
            (("помогу", "я рядом", "держись"), "support", .32, {"joy": .16, "interest": .18}, {"warmth": .14}),
            (("извини", "прости", "виноват"), "apology", .55, {"hurt": -.45, "irritation": -.35}, {"tension": -.35}),
            (("спасибо", "молодец", "умница", "классно", "круто", "офигенно", "красавица",
              "лучшая", "лучший", "шикарно", "збс", "зашибись", "пушка",
              "огонь", "бомба", "супер", "великолепно", "прекрасно", "отлично",
              "замечательно", "потрясающе", "идеально", "обалдеть", "восхитительно",
              "мне нравится", "нравишься мне"),
             "praise", .45, {"joy": .5}, {"warmth": .3}),
            # --- Profanity / aggression ---
            (("нахуй", "иди нахуй", "пошла нахуй", "пошёл нахуй", "пошел нахуй",
              "ёбаный", "ебаный", "пиздец", "сука", "блядь", "блять",
              "хуёво", "хуево", "пидор", "мразь", "тварь", "урод", "уродина",
              "ублюдок", "гнида", "шалава", "шлюха"),
             "insult", -.75, {"hurt": .7, "irritation": .55, "anger": .3}, {"trust": -.35, "tension": .5}),
            (("ненавижу", "дура", "тупая", "тупой", "заткнись", "идиотка", "идиот",
              "дебил", "дебилка", "кретин", "дурак", "дурочка"),
             "insult", -.75, {"hurt": .7, "irritation": .45}, {"trust": -.35, "tension": .5}),
            # --- Humor / laughter ---
            (("хаха", "ахаха", "ахах", "хахах", "лол", "lol", "ору", "ржу",
              "кек", "жиза", "ржака", "угар", "смешно", "ха-ха", "😂", "🤣",
              "ахахах", "хахаха", "ха ха", "смеюсь"),
             "teasing", .35, {"playfulness": .65, "joy": .2}, {"warmth": .08}),
            (("обещаю",), "promise_made", .35, {"interest": .35}, {"trust": .15}),
            (("не выполнил", "не сдержал обещание"), "broken_promise", -.65, {"hurt": .55, "anxiety": .25}, {"trust": -.4, "tension": .35}),
            (("сделал", "получилось", "закончили", "справились", "ура", "победа",
              "удалось", "наконец-то", "заработало", "ништяк"),
             "shared_success", .55, {"joy": .55, "energy": .2}, {"warmth": .16}),
            # --- Sadness / distress ---
            (("боюсь", "мне плохо", "тяжело", "грустно", "хреново", "паршиво",
              "одиноко", "не хочу ничего", "всё плохо", "депрессия",
              "мне хуёво", "мне хуево", "невыносимо", "нет сил", "устал от всего",
              "устала от всего", "опустошён", "опустошена", "тошно",
              "жить не хочу", "выгорание"),
             "vulnerability", -.25, {"sadness": .45, "anxiety": .25, "interest": .2}, {"warmth": .12}),
            (("ты ошиблась", "ты не про того", "не это"), "iris_mistake_corrected", -.12, {"embarrassment": .35, "interest": .18}, {"tension": -.03}),
            (("не согласен", "неправильно", "ерунда", "бред", "чушь", "фигня",
              "глупость", "ерунду несёшь", "ерунду несешь"),
             "disagreement", -.15, {"irritation": .15, "interest": .16}, {}),
            (("отстань", "не хочу с тобой", "отвали", "не трогай", "оставь меня",
              "не лезь", "уйди"),
             "rejection", -.55, {"hurt": .4, "sadness": .15}, {"warmth": -.2, "tension": .2}),
            # --- Frustration / annoyance (milder than insult) ---
            (("бесит эта", "ненавижу эту", "достало это", "задолбало", "заебало",
              "заколебало", "надоело", "раздражает", "бесишь", "достала",
              "достал", "опять", "ну вот опять", "блин", "чёрт", "черт",
              "ну ёмаё", "ну ёмоё", "капец", "трэш"),
             "user_frustration", -.18, {"irritation": .35, "anxiety": .08, "interest": .14}, {"warmth": .04}),
            # --- Surprise / amazement ---
            (("ого", "ни фига себе", "вау", "охренеть", "офигеть", "ничоси",
              "ничего себе", "серьёзно", "серьезно", "это реально", "не может быть",
              "обалдеть", "ни хрена себе", "ну нифига", "ну ничего себе",
              "опа", "ой", "вот это да"),
             "important_news", .25, {"interest": .55, "joy": .15}, {"warmth": .05}),
        )
        for needles, kind, valence, emotions, relations in mappings:
            if any(needle in text for needle in needles):
                return EventAppraisal(
                    event_kind=kind,
                    confidence=0.82,
                    intensity=min(1.0, 0.45 + len(text) / 500),
                    valence=valence,
                    arousal=abs(valence),
                    direction="toward_iris",
                    target_participant=participant,
                    emotion_impulses=emotions,
                    relationship_impulses=relations,
                    cause_message_ids=[message_id],
                )
        return EventAppraisal(
            event_kind="neutral",
            confidence=0.7,
            intensity=0.1,
            target_participant=participant,
            direction="unknown",
            cause_message_ids=[message_id],
        )

    @staticmethod
    def _decision(
        action: ConversationAction,
        reason: DecisionReason,
        confidence: float,
        addressedness: float,
        relevance: float,
        significance: float,
        reaction_emotion: str = "neutral",
    ) -> ConversationDecision:
        return ConversationDecision(
            action=action,
            reason=reason,
            confidence=max(0.0, min(1.0, confidence)),
            addressedness=max(0.0, min(1.0, addressedness)),
            relevance=max(0.0, min(1.0, relevance)),
            significance=max(0.0, min(1.0, significance)),
            reaction_emotion=reaction_emotion,
        )
