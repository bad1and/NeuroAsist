from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.dialogue_style import (
    DialogueStyleService,
    dialogue_style_prompt,
    has_street_voice,
)
from apps.backend.app.agents.character.protocol import legacy_result
from apps.backend.app.conversation.adjudicator import StructuredConversationAdjudicator
from apps.backend.app.conversation.schemas import (
    ConversationAction,
    ConversationDecision,
    DecisionReason,
    EventAppraisal,
)
from apps.backend.app.llm.base import LLMResponse
from apps.backend.app.schemas.character import CharacterTurn, DialogueStyleCue
from apps.backend.app.storage.timeline import TimelineHistoryAdapter, TimelineStore


def test_dialogue_style_lives_only_for_one_episode(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    first, _ = store.append_message(role="user", content="Привет", input_mode="text")
    service = DialogueStyleService(store)

    assert service.resolve(first.episode_id) == "street"
    service.apply(first.episode_id, "clean", source_message_id=first.id)
    second, _ = store.append_message(role="user", content="Продолжим", input_mode="text")
    assert second.episode_id == first.episode_id
    assert service.resolve(second.episode_id) == "clean"

    store.close_current_episode()
    third, _ = store.append_message(role="user", content="Новый разговор", input_mode="text")
    assert third.episode_id != first.episode_id
    assert service.resolve(third.episode_id) == "street"


def test_dialogue_style_never_enters_avatar_or_legacy_payload() -> None:
    turn = CharacterTurn(
        reply="Хорошо, без мата.",
        dialogue_style=DialogueStyleCue(mode="clean"),
    )

    assert "dialogue_style" not in turn.metadata_frame()
    assert "dialogue_style" not in legacy_result(turn, include_metadata=True)


def test_street_keeps_character_without_a_per_reply_vocabulary_quota() -> None:
    street = dialogue_style_prompt("street")
    assert "Можешь материться первой" in street
    assert "Мат, шутка и сленг необязательны" in street
    assert "Не вставляй мат механически" in street
    assert "матерись заметно меньше" in dialogue_style_prompt("restrained")
    assert "без мата" in dialogue_style_prompt("clean")


@pytest.mark.parametrize(
    "reply",
    [
        "Ну и дичь.",
        "Ща разберёмся с этой хренью.",
    ],
)
def test_street_voice_quality_check_accepts_slang_or_profanity(reply: str) -> None:
    assert has_street_voice(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "Здорово, Федя. Чего хотел?",
        "Ну давай поболтаем. О чём думаешь?",
        "Ага, мрачно.",
    ],
)
def test_street_voice_quality_check_rejects_sterile_casual_replies(reply: str) -> None:
    assert not has_street_voice(reply)




class _SequencedStreetProvider:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0
        self.message_batches = []

    async def generate(self, messages):
        self.message_batches.append(messages)
        reply = self.replies[self.calls]
        self.calls += 1
        return LLMResponse(
            content=json.dumps({
                "reply": reply,
                "emotion": "neutral",
                "intent": "casual_chat",
            }, ensure_ascii=False),
            model="test",
        )

    async def stream(self, messages):
        self.message_batches.append(messages)
        reply = self.replies[self.calls]
        self.calls += 1
        yield reply


@pytest.mark.anyio
async def test_batch_plain_reply_is_accepted_without_style_retry(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    provider = _SequencedStreetProvider([
        "Ага, мрачно.",
    ])
    agent = CharacterAgent(
        provider,
        TimelineHistoryAdapter(store),
        8,
        dialogue_style_service=DialogueStyleService(store),
    )

    result = await agent.handle_user_message("session", "пиздец")

    assert provider.calls == 1
    assert result["reply"] == "Ага, мрачно."


@pytest.mark.anyio
async def test_live_plain_opening_reaches_output_without_style_retry(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    provider = _SequencedStreetProvider([
        "Здорово, Федя. Чего хотел?",
    ])
    agent = CharacterAgent(
        provider,
        TimelineHistoryAdapter(store),
        8,
        dialogue_style_service=DialogueStyleService(store),
    )

    chunks = [chunk async for chunk in agent.stream_user_message("session", "Здорово")]

    assert provider.calls == 1
    assert "".join(chunks) == "Здорово, Федя. Чего хотел?"


class _BatchStyleProvider:
    async def generate(self, messages):
        return LLMResponse(
            content=json.dumps({
                "protocol_version": 3,
                "reply": "Ладно, буду мягче.",
                "dialogue_style": {"mode": "restrained"},
            }, ensure_ascii=False),
            model="test",
        )


@pytest.mark.anyio
async def test_batch_cue_applies_to_current_episode_and_stays_hidden(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    styles = DialogueStyleService(store)
    agent = CharacterAgent(
        _BatchStyleProvider(), TimelineHistoryAdapter(store), 8,
        dialogue_style_service=styles,
    )

    result = await agent.handle_user_message("session", "Поменьше матерись")
    episode_id = store.current_episode()["id"]

    assert result["reply"] == "Ладно, буду мягче."
    assert "dialogue_style" not in result
    assert styles.resolve(str(episode_id)) == "restrained"


class _LiveStyleProvider:
    def __init__(self) -> None:
        self.payload = None

    async def generate_structured(self, messages, *, temperature=0.0):
        self.payload = json.loads(messages[-1].content)
        return LLMResponse(content=json.dumps({
            "version": 1,
            "decision": {
                "version": 1, "action": "respond", "reason": "direct_address",
                "confidence": .9, "addressedness": .9, "relevance": .8,
                "significance": .4, "reaction_emotion": "neutral",
                "defer_for_ms": None, "expires_in_ms": None,
            },
            "appraisal": {"version": 2, "event_kind": "neutral"},
            "dialogue_style": {"mode": "clean"},
        }), model="test")


@pytest.mark.anyio
async def test_live_adjudication_receives_context_and_returns_private_cue() -> None:
    provider = _LiveStyleProvider()
    adjudicator = StructuredConversationAdjudicator(provider)
    fallback_decision = ConversationDecision(
        action=ConversationAction.RESPOND,
        reason=DecisionReason.DIRECT_ADDRESS,
        confidence=.9,
        addressedness=.9,
        relevance=.8,
        significance=.4,
    )
    result = await adjudicator.adjudicate(
        "Давай без мата",
        fallback_decision=fallback_decision,
        fallback_appraisal=EventAppraisal(),
        cause_message_id="message-1",
        speaker_role="primary",
        previous_assistant_text="Ну и что дальше?",
        relationship_context="warmth=0.5; tension=0.1",
        current_dialogue_style="street",
    )

    assert result.dialogue_style == DialogueStyleCue(mode="clean")
    assert provider.payload["previous_assistant_text"] == "Ну и что дальше?"
    assert provider.payload["current_dialogue_style"] == "street"
