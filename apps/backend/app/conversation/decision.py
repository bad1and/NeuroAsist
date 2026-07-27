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


class ConversationDecisionEngine:
    """Hard gates plus deterministic engagement scoring.

    Ambiguous cases may later be enriched by a structured LLM adjudicator; the
    reducer remains the authority and always has a conservative local fallback.
    """

    _name = re.compile(r"(?iu)(?:^|[\s,!.?—-])(?:iris|ирис|ириска)(?:$|[\s,!.?—-])")
    _invitation = re.compile(
        r"(?iu)\b(?:что думаешь|как считаешь|тво[её] мнение|скажи|ответь|прокомментируй|а ты)\b"
    )
    _implicit_request = re.compile(
        r"(?iu)(?:"
        r"\b(?:можешь|могла\s+бы|подскажи|расскажи|объясни|покажи|скинь|пришли|"
        r"дай|помоги|посоветуй|найди|открой|включи|выключи)\b|"
        r"^\s*(?:а\s+)?(?:что|кто|где|куда|откуда|когда|почему|зачем|как|"
        r"какой|какая|какие|сколько|чем)\b"
        r")"
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
        r"(?P<name>[а-яёa-z]{2,20})[\s,]+"
        r"(?:ты|вы|можешь|можете|зайди|зайдите|подойди|подойдите|включи|"
        r"включите|выключи|выключите|скажи|скажите|посмотри|посмотрите|"
        r"давай|давайте|привет|пока)\b"
    )
    _non_names = {
        "iris", "ирис", "ириска", "а", "ну", "так", "да", "нет", "блин",
        "слушай", "смотри", "кстати", "короче",
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

    def is_addressed_to_other(self, transcript: str) -> bool:
        """Detect a vocative aimed at a nearby person rather than Iris."""
        text = transcript.strip()
        if self._known_other_name.search(text):
            return True
        match = self._generic_other_vocative.search(text)
        return bool(match and match.group("name").casefold() not in self._non_names)

    @staticmethod
    def appraise(transcript: str, message_id: str, participant: str = "primary") -> EventAppraisal:
        text = transcript.casefold()
        mappings = (
            (("извини", "прости"), "apology", 0.55, {"hurt": -0.45, "irritation": -0.35}, {"trust": 0.25, "tension": -0.35}),
            (("спасибо", "молодец", "умница"), "praise", 0.45, {"joy": 0.5}, {"warmth": 0.3}),
            (("ненавижу", "дура", "тупая", "заткнись"), "insult", -0.75, {"hurt": 0.7, "irritation": 0.45}, {"trust": -0.35, "tension": 0.5}),
            (("обещаю",), "promise", 0.35, {"interest": 0.35}, {"trust": 0.15}),
        )
        for needles, kind, valence, emotions, relations in mappings:
            if any(needle in text for needle in needles):
                return EventAppraisal(
                    event_kind=kind,
                    confidence=0.82,
                    intensity=min(1.0, 0.45 + len(text) / 500),
                    valence=valence,
                    arousal=abs(valence),
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
