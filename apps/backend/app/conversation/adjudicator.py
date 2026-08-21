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
Схема верхнего уровня:
{"version":1,"decision":{"version":1,"action":"observe","reason":"ambient_speech",
"confidence":0.8,"addressedness":0.1,"relevance":0.3,"significance":0.2,
"reaction_emotion":"neutral","defer_for_ms":null,"expires_in_ms":null},
"appraisal":{"version":1,"event_kind":"neutral","target_participant":"primary",
"confidence":0.7,"intensity":0.1,"valence":0.0,"arousal":0.0,
"emotion_impulses":{},"relationship_impulses":{},"cause_message_ids":[]}}
Не возвращай скрытые рассуждения. Все числа должны находиться в диапазонах схемы."""

class StructuredConversationAdjudicator:
    def __init__(
        self,
        provider: LLMProvider | None,
        *,
        first_timeout: float = 1.5,
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
