import pytest

from apps.backend.app.conversation.adjudicator import StructuredConversationAdjudicator
from apps.backend.app.conversation.schemas import (
    ConversationAction,
    ConversationDecision,
    DecisionReason,
    EventAppraisal,
)
from apps.backend.app.llm.base import LLMResponse


class _InvalidAdjudicationProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(self, _messages, *, temperature: float = 0.0):
        self.calls += 1
        return LLMResponse(content="not-json", model="test")


@pytest.mark.anyio
async def test_adjudication_uses_fallback_without_a_second_llm_request() -> None:
    provider = _InvalidAdjudicationProvider()
    adjudicator = StructuredConversationAdjudicator(provider)
    fallback_decision = ConversationDecision(
        action=ConversationAction.OBSERVE,
        reason=DecisionReason.AMBIENT_SPEECH,
        confidence=0.7,
        addressedness=0.1,
        relevance=0.2,
        significance=0.1,
    )
    fallback_appraisal = EventAppraisal()

    decision, appraisal, source = await adjudicator.adjudicate(
        "Наверное, завтра будет дождь",
        fallback_decision=fallback_decision,
        fallback_appraisal=fallback_appraisal,
        cause_message_id="message-1",
        speaker_role="unknown",
    )

    assert provider.calls == 1
    assert source == "deterministic_fallback"
    assert decision == fallback_decision
    assert appraisal == fallback_appraisal
