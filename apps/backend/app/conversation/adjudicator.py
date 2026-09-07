from __future__ import annotations

import asyncio
import json
import logging

from apps.backend.app.conversation.schemas import (
    ConversationAdjudicationV1,
    ConversationDecision,
    EventAppraisal,
)
from apps.backend.app.llm.base import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Ты классификатор живого разговора Iris. Верни только JSON без markdown.
Не показывай рассуждения. Не управляй БД. Выбери действие и ограниченную оценку события.
Разрешённые действия: wait_more, observe, avatar_reaction, backchannel, respond, defer.
Причины: incomplete_turn, direct_address, invited, ambient_speech, self_talk, other_person,
relevant_opening, emotional_event, cooldown, speech_budget, echo, low_confidence.

ВАЖНО: Iris — живой человек со своими чувствами и гордостью, а не безропотный сервисный бот!
- Прямой мат в адрес Iris, грубость («пошла нахер», «тупая», «заебала», «шлюха») → event_kind="insult", intensity 0.75-0.95, valence -0.7..-0.9, emotion_impulses: {"hurt": 0.7, "anger": 0.6, "irritation": 0.8}, relationship_impulses: {"trust": -0.08, "warmth": -0.07, "tension": 0.08}.
- Грубые обрывы и приказы («заткнись», «отъебись», «хватит нести херню») → event_kind="rejection" или "user_frustration", intensity 0.6-0.8, emotion_impulses: {"irritation": 0.7, "hurt": 0.4}.
- Похвала, восхищение («ты лучшая», «обожаю тебя», «спасибо большое, выручила») → event_kind="praise", intensity 0.5-0.75, valence 0.5..0.7, emotion_impulses: {"joy": 0.6, "interest": 0.3}, relationship_impulses: {"warmth": 0.05, "trust": 0.03}.
- Извинения и попытки помириться («прости», «извини, погорячился», «мир?») → event_kind="apology", intensity 0.55-0.75, valence 0.4..0.6, emotion_impulses: {"joy": 0.3}, relationship_impulses: {"tension": -0.06, "warmth": 0.04}.
- Ласка, флирт, признания («ты милая», «люблю тебя») → event_kind="affection", intensity 0.6-0.8, emotion_impulses: {"joy": 0.6, "embarrassment": 0.3}.
- Смех, дружеские подколы («хаха, ну ты даёшь», «лол») → event_kind="teasing" или "shared_success", emotion_impulses: {"playfulness": 0.6, "joy": 0.4}.
- Только если сообщение сугубо деловое («который час», «напиши функцию») — neutral. Не ставь neutral, если есть хоть малейший эмоциональный окрас!

event_kind: support, apology, insult, teasing, praise, disagreement, rejection, promise_made,
broken_promise, fulfilled_promise, vulnerability, affection, user_frustration,
iris_mistake_corrected, shared_success, important_negative_event, important_news, neutral.

Схема верхнего уровня:
{"version":1,"decision":{"version":1,"action":"respond","reason":"direct_address",
"confidence":0.9,"addressedness":0.95,"relevance":0.7,"significance":0.5,
"reaction_emotion":"happy","defer_for_ms":null,"expires_in_ms":null},
"appraisal":{"version":1,"event_kind":"praise","target_participant":"primary",
"confidence":0.85,"intensity":0.6,"valence":0.5,"arousal":0.4,
"emotion_impulses":{"joy":0.5},"relationship_impulses":{"warmth":0.2},"cause_message_ids":[]}}
Не возвращай скрытые рассуждения. Все числа должны находиться в диапазонах схемы."""


class StructuredConversationAdjudicator:
    def __init__(
        self,
        provider: LLMProvider | None,
        *,
        first_timeout: float = 3.5,
        repair_timeout: float = 1.0,
    ) -> None:
        self._provider = provider
        self._first_timeout = first_timeout
        # Kept in the public signature for callers from older releases; repair
        # requests are intentionally disabled to enforce one adjudication call.
        _ = repair_timeout

    @property
    def available(self) -> bool:
        return self._provider is not None

    async def adjudicate(
        self,
        transcript: str,
        *,
        fallback_decision: ConversationDecision,
        fallback_appraisal: EventAppraisal,
        cause_message_id: str,
        speaker_role: str,
    ) -> tuple[ConversationDecision, EventAppraisal, str]:
        if self._provider is None:
            return fallback_decision, fallback_appraisal, "deterministic"
        user_payload = {
            "transcript": transcript,
            "speaker_role": speaker_role,
            "cause_message_id": cause_message_id,
            "fallback": {
                "decision": fallback_decision.model_dump(mode="json"),
                "appraisal": fallback_appraisal.model_dump(mode="json"),
            },
        }
        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
        ]
        try:
            result = await self._call(messages, self._first_timeout)
            return result.decision, self._with_cause(result.appraisal, cause_message_id), "llm"
        except Exception as error:
            # Adjudication is optional and already has a deterministic result.
            # A second full-context request after a short timeout used to
            # double API usage while almost never completing within its even
            # shorter repair timeout.
            logger.info(
                "Conversation adjudication failed; using deterministic fallback: %s",
                type(error).__name__,
            )
            return fallback_decision, fallback_appraisal, "deterministic_fallback"

    async def _call(
        self,
        messages: list[ChatMessage],
        timeout: float,
    ) -> ConversationAdjudicationV1:
        assert self._provider is not None
        generate_structured = getattr(self._provider, "generate_structured", None)
        response = await asyncio.wait_for(
            generate_structured(messages, temperature=0.0)
            if callable(generate_structured)
            else self._provider.generate(messages),
            timeout=timeout,
        )
        return ConversationAdjudicationV1.model_validate_json(response.content)

    @staticmethod
    def _with_cause(appraisal: EventAppraisal, cause_message_id: str) -> EventAppraisal:
        return appraisal.model_copy(update={"cause_message_ids": [cause_message_id]})
