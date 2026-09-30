from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Iterator

from apps.backend.app.conversation.schemas import (
    ConversationAdjudicationV1,
    ConversationDecision,
    EventAppraisal,
)
from apps.backend.app.llm.base import ChatMessage, LLMProvider
from apps.backend.app.schemas.character import DialogueStyleCue

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Ты смысловой классификатор живого разговора Iris. Верни только JSON без markdown.
Не показывай рассуждения. Не управляй БД. Выбери действие и ограниченную оценку события.
Разрешённые действия: wait_more, observe, avatar_reaction, backchannel, respond, defer.
Причины: incomplete_turn, direct_address, invited, ambient_speech, self_talk, other_person,
relevant_opening, emotional_event, cooldown, speech_budget, echo, low_confidence.

Оценивай намерение, адресат, синтаксис, предыдущий ход и отношения — не наличие слова.
- Дружеский мат, грубоватое приветствие («Здорово, заебал»), самоирония, цитата и ругань на ситуацию/код → neutral, teasing или shared_success. Мат сам по себе не меняет настроение.
- Критика без намеренного унижения → disagreement или user_frustration, но не insult.
- Только намеренное унижение Iris, угроза или повторное давление после обозначенной границы → insult/rejection с hurt/anger и снижением отношений.
- Похвала, восхищение («ты лучшая», «обожаю тебя», «спасибо большое, выручила») → event_kind="praise", intensity 0.5-0.75, valence 0.5..0.7, emotion_impulses: {"joy": 0.6, "interest": 0.3}, relationship_impulses: {"warmth": 0.05, "trust": 0.03}.
- Извинения и попытки помириться («прости», «извини, погорячился», «мир?») → event_kind="apology", intensity 0.55-0.75, valence 0.4..0.6, emotion_impulses: {"joy": 0.3}, relationship_impulses: {"tension": -0.06, "warmth": 0.04}.
- Ласка, флирт, признания («ты милая», «люблю тебя») → event_kind="affection", intensity 0.6-0.8, emotion_impulses: {"joy": 0.6, "embarrassment": 0.3}.
- Смех, явная шутка, ирония, мем или дружеский подкол, включая чёрный юмор и мат без атаки на Iris, → event_kind="teasing" или "shared_success", emotion_impulses: {"playfulness": 0.6, "joy": 0.4}. Мрачная тема и грубые слова сами по себе не делают шутку угрозой или оскорблением.
- Нейтральная реплика вполне может быть neutral; не выдумывай эмоциональное событие.

dialogue_style — необязательное скрытое поле. Возвращай его только при явной просьбе изменить собственную речь Iris: «поменьше матерись» → {"mode":"restrained"}, «без мата» → clean, «матерись как обычно» → street. Обсуждение мата, цитата или чужой текст ничего не меняют.

event_kind: support, apology, insult, teasing, praise, disagreement, rejection, promise_made,
broken_promise, fulfilled_promise, vulnerability, affection, user_frustration,
iris_mistake_corrected, shared_success, important_negative_event, important_news, neutral.

Схема верхнего уровня:
{"version":1,"decision":{"version":1,"action":"respond","reason":"direct_address",
"confidence":0.9,"addressedness":0.95,"relevance":0.7,"significance":0.5,
"reaction_emotion":"happy","defer_for_ms":null,"expires_in_ms":null},
"appraisal":{"version":1,"event_kind":"praise","target_participant":"primary",
"confidence":0.85,"intensity":0.6,"valence":0.5,"arousal":0.4,
"emotion_impulses":{"joy":0.5},"relationship_impulses":{"warmth":0.2},"cause_message_ids":[]},"dialogue_style":null}
Не возвращай скрытые рассуждения. Все числа должны находиться в диапазонах схемы."""


@dataclass(frozen=True)
class AdjudicationResult:
    decision: ConversationDecision
    appraisal: EventAppraisal
    source: str
    dialogue_style: DialogueStyleCue | None = None

    def __iter__(self) -> Iterator[object]:
        # Preserve the established three-value public unpacking contract.
        yield self.decision
        yield self.appraisal
        yield self.source


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
        previous_assistant_text: str | None = None,
        relationship_context: str | None = None,
        current_dialogue_style: str = "street",
    ) -> AdjudicationResult:
        if self._provider is None:
            return AdjudicationResult(fallback_decision, fallback_appraisal, "deterministic")
        user_payload = {
            "transcript": transcript,
            "speaker_role": speaker_role,
            "cause_message_id": cause_message_id,
            "previous_assistant_text": (previous_assistant_text or "")[-800:],
            "relationship_context": (relationship_context or "")[-800:],
            "current_dialogue_style": current_dialogue_style,
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
            return AdjudicationResult(
                result.decision,
                self._with_cause(result.appraisal, cause_message_id),
                "llm",
                result.dialogue_style,
            )
        except Exception as error:
            # Adjudication is optional and already has a deterministic result.
            # A second full-context request after a short timeout used to
            # double API usage while almost never completing within its even
            # shorter repair timeout.
            logger.info(
                "Conversation adjudication failed; using deterministic fallback: %s",
                type(error).__name__,
            )
            return AdjudicationResult(
                fallback_decision,
                fallback_appraisal,
                "deterministic_fallback",
            )

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
