from __future__ import annotations

import sqlite3
import json
import os
import asyncio
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.backend.app.conversation.decision import ConversationDecisionEngine, DecisionContext
from apps.backend.app.conversation.schemas import ConversationAction, SpeakerRole
from apps.backend.app.conversation.speaker import SpeakerRoleEstimator
from apps.backend.app.conversation.service import LiveConversationService
from apps.backend.app.conversation.state import AffectState, CharacterStateReducer, ParticipantState
from apps.backend.app.conversation.turn import SmartTurnDetector
from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import LLMResponse
from apps.backend.app.model_manager.service import ModelManager
from apps.backend.app.storage.timeline import LATEST_SCHEMA_VERSION, TimelineStore


def runtime(**overrides):
    defaults = {
        "memory_incognito": False,
        "live_conversation_mood_recovery": "natural",
        "live_conversation_engagement": "balanced",
        "live_conversation_participant_mode": "one_to_one",
        "live_conversation_address_strictness": "balanced",
        "live_conversation_echo_mode": "auto",
    }
    return SimpleNamespace(**{**defaults, **overrides})


def test_live_schema_is_additive_and_idempotent(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    store.init_db()

    with sqlite3.connect(tmp_path / "timeline.sqlite3") as connection:
        versions = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert versions == [
        (version,) for version in (*range(1, 7), *range(10, LATEST_SCHEMA_VERSION + 1))
    ]
    assert {
        "character_state_snapshots",
        "character_state_events",
        "character_participant_states",
        "conversation_observations",
    } <= tables


def test_schema_v10_repairs_database_with_preexisting_versions(tmp_path: Path) -> None:
    database = tmp_path / "timeline.sqlite3"
    store = TimelineStore(database)
    store.init_db()
    stored, _ = store.append_message(role="user", content="Не потеряй меня", input_mode="text")

    with sqlite3.connect(database) as connection:
        for table in (
            "conversation_observations",
            "character_participant_states",
            "character_state_events",
            "character_state_snapshots",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version = 10")
        connection.executemany(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            [(version, "2026-01-01T00:00:00+00:00") for version in (7, 8, 9)],
        )

    store.init_db()

    with sqlite3.connect(database) as connection:
        versions = {
            row[0] for row in connection.execute("SELECT version FROM schema_migrations")
        }
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        message = connection.execute(
            "SELECT content FROM conversation_messages WHERE id = ?",
            (stored.id,),
        ).fetchone()

    assert versions == set(range(1, LATEST_SCHEMA_VERSION + 1))
    assert {
        "character_state_snapshots",
        "character_state_events",
        "character_participant_states",
        "conversation_observations",
    } <= tables
    assert message == ("Не потеряй меня",)


def test_direct_address_bypasses_cooldown() -> None:
    decision = ConversationDecisionEngine().decide(
        "Ирис, что думаешь?",
        DecisionContext(cooldown_active=True, speech_budget_exceeded=True),
    )
    assert decision.action is ConversationAction.RESPOND


@pytest.mark.anyio
async def test_live_conversation_sqlite_work_stays_off_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    call_threads: list[int] = []
    for method_name in (
        "load_character_state_snapshot",
        "load_participant_states",
        "append_message",
        "save_conversation_observation",
        "set_observation_decision",
        "save_character_state_snapshot",
        "upsert_participant_state",
        "append_character_state_event",
    ):
        original = getattr(store, method_name)

        def record_thread(*args, _original=original, **kwargs):
            call_threads.append(threading.get_ident())
            return _original(*args, **kwargs)

        monkeypatch.setattr(store, method_name, record_thread)

    service = LiveConversationService(store, runtime())
    event_loop_thread = threading.get_ident()

    result = await service.ingest_observation(
        session_id="session",
        transcript="Ирис, как у тебя дела?",
        language="ru",
    )

    assert result.message is not None
    assert len(call_threads) >= 5
    assert all(thread_id != event_loop_thread for thread_id in call_threads)


def test_group_ambient_speech_is_observed() -> None:
    decision = ConversationDecisionEngine().decide(
        "Положи это на стол, пожалуйста.",
        DecisionContext(speaker_role=SpeakerRole.OTHER, speaker_confidence=0.88),
    )
    assert decision.action is ConversationAction.OBSERVE


def test_one_to_one_request_without_name_is_an_implicit_address() -> None:
    engine = ConversationDecisionEngine()
    decision = engine.decide(
        "а можешь скинуть ссылку на него",
        DecisionContext(
            addressedness=0.82,
            implicit_address=engine.is_implicit_address(
                "а можешь скинуть ссылку на него"
            ),
        ),
    )
    assert decision.action is ConversationAction.RESPOND
    assert decision.reason.value == "invited"


def test_stt_question_without_punctuation_is_an_implicit_address() -> None:
    engine = ConversationDecisionEngine()
    transcript = "как найти это приложение"
    decision = engine.decide(
        transcript,
        DecisionContext(
            addressedness=0.82,
            implicit_address=engine.is_implicit_address(transcript),
        ),
    )
    assert decision.action is ConversationAction.RESPOND


def test_question_word_is_not_mistaken_for_another_person_vocative() -> None:
    engine = ConversationDecisionEngine()
    transcript = "откуда ты знаешь про шины и босса это вообще про что"
    assert engine.is_addressed_to_other(transcript) is False
    assert engine.is_implicit_address(transcript) is True


@pytest.mark.parametrize(
    "transcript",
    [
        "а какую ты мне модель посоветовала я не помню",
        "какого ты провайдера советовала",
        "каким ты способом это делала",
        "которую ты версию имела в виду",
    ],
)
def test_inflected_question_words_are_implicit_iris_addresses(
    transcript: str,
) -> None:
    engine = ConversationDecisionEngine()
    analysis = engine.analyze_addressing(transcript)

    assert analysis.kind == "implicit_iris"
    assert analysis.other_person is False
    assert analysis.implicit_iris is True


def test_unknown_other_name_requires_command_shaped_evidence() -> None:
    engine = ConversationDecisionEngine()

    assert engine.is_addressed_to_other("Арсен ты можешь включить демку") is True
    assert engine.is_addressed_to_other("Арсен, привет") is True
    assert engine.is_addressed_to_other("какую ты мне модель советовала") is False


@pytest.mark.anyio
async def test_screenshot_model_question_responds_without_second_wake_word(
    tmp_path: Path,
) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())

    result = await service.ingest_observation(
        session_id="session",
        transcript="а какую ты мне модель посоветовала я не помню",
        language="ru",
    )

    assert result.decision.action is ConversationAction.RESPOND
    assert result.decision.reason.value == "invited"
    observations = store.recent_conversation_observations("session")
    assert observations[0]["metadata"]["addressing_reasons"] == [
        "interrogative_followup"
    ]


def test_discourse_filler_and_stt_iris_alias_remain_direct_addresses() -> None:
    engine = ConversationDecisionEngine()
    assert engine.is_implicit_address("кстати ну как меня зовут ты же помнишь") is True
    assert engine.addressedness("иреск ты помнишь как меня зовут") == 1.0
    assert engine.is_addressed_to_other("иреск ты помнишь как меня зовут") is False


def test_vocative_to_another_person_overrides_implicit_request() -> None:
    engine = ConversationDecisionEngine()
    transcript = "олег ты можешь мне включить демку"
    decision = engine.decide(
        transcript,
        DecisionContext(
            addressedness=0.82,
            implicit_address=True,
            addressed_to_other=engine.is_addressed_to_other(transcript),
        ),
    )
    assert decision.action is ConversationAction.OBSERVE
    assert decision.reason.value == "other_person"


def test_relationship_delta_is_bounded_and_diminishes() -> None:
    engine = ConversationDecisionEngine()
    reducer = CharacterStateReducer()
    appraisal = engine.appraise("Ты тупая", "message-1")
    state = ParticipantState()

    state, first = reducer.apply_relationship(state, appraisal)
    state, repeated = reducer.apply_relationship(state, appraisal, repeated_events=3)

    assert abs(first["trust"]) <= 0.03
    assert abs(repeated["trust"]) < abs(first["trust"])
    assert 0 <= state.tension <= 1


def test_affect_decay_uses_elapsed_time() -> None:
    reducer = CharacterStateReducer()
    state = AffectState(joy=0.8, updated_at="2026-01-01T00:00:00+00:00")
    reducer.decay(state, now=__import__("datetime").datetime(2026, 1, 1, 0, 12, tzinfo=__import__("datetime").UTC))
    assert state.joy == pytest.approx(0.4)


@pytest.mark.anyio
async def test_silent_observation_is_persisted_before_decision(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    generation = await service.speech_started("session")

    result = await service.ingest_observation(
        session_id="session",
        transcript="Я просто думаю вслух.",
        language="ru",
        expected_generation=generation,
    )

    assert result.message is not None
    assert result.decision.action is ConversationAction.OBSERVE
    observations = store.recent_conversation_observations("session")
    assert observations[0]["message_id"] == result.message.id
    assert observations[0]["decision_action"] == "observe"


@pytest.mark.anyio
async def test_one_to_one_spoken_request_responds_without_saying_iris(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())

    result = await service.ingest_observation(
        session_id="session",
        transcript="а можешь скинуть ссылку на него",
        language="ru",
    )

    assert result.decision.action is ConversationAction.RESPOND
    assert result.decision.reason.value == "invited"
    observations = store.recent_conversation_observations("session")
    assert observations[0]["addressedness"] == pytest.approx(0.82)
    assert observations[0]["decision_action"] == "respond"


@pytest.mark.anyio
async def test_group_contextual_implicit_request_continues_recent_iris_turn(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(
        store,
        runtime(live_conversation_participant_mode="group"),
    )
    session = service.session("session")
    session.last_iris_activity_at = __import__("time").monotonic()
    session.last_generated_assistant_reply = "Привет, Федь. Как ты?"

    result = await service.ingest_observation(
        session_id="session",
        transcript=(
            "да нормально вот расскажи че ты допустим какие игры ты любишь "
            "и сколько у тебя на рдоте"
        ),
        language="ru",
    )

    assert result.decision.action is ConversationAction.RESPOND
    assert result.decision.reason.value == "invited"
    assert result.decision.addressedness >= 0.82
    observations = store.recent_conversation_observations("session")
    assert observations[0]["metadata"]["addressing_reasons"] == [
        "implicit_request",
        "recent_dialogue_continuity"
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "transcript",
    [
        "Олег, расскажи какие игры ты любишь",
        "не обращай внимания, расскажи какие игры ты любишь",
        "расскажи какие игры ты любишь",
    ],
)
async def test_group_implicit_request_without_safe_dialogue_context_stays_observed(
    tmp_path: Path,
    transcript: str,
) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(
        store,
        runtime(live_conversation_participant_mode="group"),
    )

    result = await service.ingest_observation(
        session_id="session",
        transcript=transcript,
        language="ru",
    )

    assert result.decision.action is ConversationAction.OBSERVE


@pytest.mark.anyio
async def test_group_implicit_request_after_iris_question_needs_reply_evidence(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(
        store,
        runtime(live_conversation_participant_mode="group"),
    )
    session = service.session("session")
    session.last_iris_activity_at = __import__("time").monotonic()
    session.last_generated_assistant_reply = "Как у тебя дела?"

    result = await service.ingest_observation(
        session_id="session",
        transcript="расскажи про игры",
        language="ru",
    )

    assert result.decision.action is ConversationAction.OBSERVE


@pytest.mark.anyio
async def test_follow_up_to_recent_iris_turn_keeps_conversation_addressed(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    session = service.session("session")
    session.last_iris_activity_at = __import__("time").monotonic()

    result = await service.ingest_observation(
        session_id="session",
        transcript="так в смысле я разраб если что",
        language="ru",
    )

    assert result.decision.action is ConversationAction.RESPOND
    assert result.decision.reason.value == "invited"
    observations = store.recent_conversation_observations("session")
    assert observations[0]["metadata"]["addressing_reasons"] == ["recent_dialogue_continuity"]


@pytest.mark.anyio
async def test_one_to_one_primary_speech_responds_without_a_name(
    tmp_path: Path,
) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(
        store,
        runtime(live_conversation_address_strictness="strict"),
    )

    result = await service.ingest_observation(
        session_id="session",
        transcript="мы завтра созвонимся в десять",
        language="ru",
    )

    assert result.decision.action is ConversationAction.RESPOND
    assert result.decision.reason.value == "invited"
    observations = store.recent_conversation_observations("session")
    assert observations[0]["metadata"]["addressing_reasons"] == [
        "one_to_one_primary_speech"
    ]


@pytest.mark.anyio
async def test_short_answer_to_recent_iris_question_remains_a_followup(
    tmp_path: Path,
) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    session = service.session("session")
    session.last_iris_activity_at = __import__("time").monotonic()
    session.last_generated_assistant_reply = "Какую модель ты хочешь поставить?"

    result = await service.ingest_observation(
        session_id="session",
        transcript="Whisper третьей версии",
        language="ru",
    )

    assert result.decision.action is ConversationAction.RESPOND
    observations = store.recent_conversation_observations("session")
    assert observations[0]["metadata"]["addressing_reasons"] == [
        "recent_dialogue_continuity"
    ]


@pytest.mark.anyio
async def test_balanced_followup_window_expires_after_twenty_five_seconds(
    tmp_path: Path,
) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    session = service.session("session")
    session.last_iris_activity_at = __import__("time").monotonic() - 26

    result = await service.ingest_observation(
        session_id="session",
        transcript="так в смысле я разраб если что",
        language="ru",
    )

    assert result.decision.action is ConversationAction.RESPOND


@pytest.mark.anyio
async def test_other_person_address_suppresses_followups_until_iris_is_called(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(
        store,
        runtime(live_conversation_participant_mode="group"),
    )
    session = service.session("session")
    session.last_iris_activity_at = __import__("time").monotonic()

    directed_elsewhere = await service.ingest_observation(
        session_id="session",
        transcript="олег зайди на демку",
        language="ru",
    )
    ambient_followup = await service.ingest_observation(
        session_id="session",
        transcript="кто-то уже зашел",
        language="ru",
    )
    called_back = await service.ingest_observation(
        session_id="session",
        transcript="ирис а ты что думаешь",
        language="ru",
    )

    assert directed_elsewhere.decision.action is ConversationAction.OBSERVE
    assert directed_elsewhere.decision.reason.value == "other_person"
    assert ambient_followup.decision.action is ConversationAction.OBSERVE
    assert ambient_followup.decision.reason.value == "other_person"
    assert called_back.decision.action is ConversationAction.RESPOND


@pytest.mark.anyio
async def test_other_person_speech_does_not_change_iris_state_or_enter_memory(tmp_path: Path) -> None:
    class RecordingMemory:
        uses_background_extraction = False

        def __init__(self) -> None:
            self.scheduled: list[str] = []

        def schedule_extraction(self, message) -> None:
            self.scheduled.append(message.id)

    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    memory = RecordingMemory()
    service = LiveConversationService(
        store,
        runtime(live_conversation_participant_mode="group"),
        memory_service=memory,
    )
    session = service.session("session")
    initial_affect = session.affect.as_dict()
    initial_participant = session.participants["primary"].as_dict()

    result = await service.ingest_observation(
        session_id="session",
        transcript="Олег, ты вообще тупой, я же просил включить дэмку",
        language="ru",
    )

    assert result.decision.action is ConversationAction.OBSERVE
    assert result.decision.reason.value == "other_person"
    assert session.affect.as_dict() == initial_affect
    assert session.participants["primary"].as_dict() == initial_participant
    assert memory.scheduled == []


@pytest.mark.anyio
async def test_late_observation_generation_cannot_commit(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    stale_generation = await service.speech_started("session")
    await service.speech_started("session")

    result = await service.ingest_observation(
        session_id="session",
        transcript="Старый результат STT",
        language="ru",
        expected_generation=stale_generation,
    )

    assert result.message is None
    assert store.recent_conversation_observations("session") == []


@pytest.mark.anyio
async def test_incognito_observation_stays_ephemeral(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime(memory_incognito=True))
    generation = await service.speech_started("session")

    result = await service.ingest_observation(
        session_id="session",
        transcript="Ирис, ответь",
        language="ru",
        expected_generation=generation,
    )

    assert result.message is None
    assert result.decision.action is ConversationAction.RESPOND
    assert store.recent_conversation_observations("session") == []


@pytest.mark.anyio
async def test_smart_turn_missing_model_degrades_safely(tmp_path: Path) -> None:
    detector = SmartTurnDetector(tmp_path / "missing.onnx")
    result = await detector.analyze(b"\0\0" * 16000, 16000)
    assert result.complete is False
    assert result.fallback is True
    assert result.provider == "heuristic"


@pytest.mark.anyio
async def test_assistant_turn_commits_only_acknowledged_playback(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    generation = await service.speech_started("session")
    observation = await service.ingest_observation(
        session_id="session",
        transcript="Ирис, ответь",
        language="ru",
        expected_generation=generation,
    )

    await service.playback_segment_finished(
        "session",
        "Да, я здесь.",
        observation.utterance_id,
        generation,
    )
    messages, _ = store.list_messages(20)
    assert [message.role for message in messages] == ["user"]

    await service.playback_finished("session", observation.utterance_id)
    messages, _ = store.list_messages(20)
    assert [(message.role, message.status) for message in messages] == [
        ("user", "completed"),
        ("assistant", "completed"),
    ]


@pytest.mark.anyio
async def test_avatar_ack_commits_generated_reply_and_keeps_it_for_correction_context(
    tmp_path: Path,
) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    generation = await service.speech_started("session")
    observation = await service.ingest_observation(
        session_id="session",
        transcript="Ирис, кто такой Братишкин?",
        language="ru",
        expected_generation=generation,
    )
    generated = "Не уверена, какого именно Братишкина ты имеешь в виду."

    await service.assistant_text_generated(
        "session",
        observation.utterance_id,
        generation,
        generated,
    )
    await service.avatar_playback_finished(observation.utterance_id)

    messages, _ = store.list_messages(20)
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Ирис, кто такой Братишкин?"),
        ("assistant", generated),
    ]
    followup = await service.ingest_observation(
        session_id="session",
        transcript="ты не про того",
        language="ru",
    )
    assert generated in followup.state_context


@pytest.mark.anyio
async def test_barge_in_commits_only_acknowledged_prefix_as_interrupted(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    generation = await service.speech_started("session")
    observation = await service.ingest_observation(
        session_id="session",
        transcript="Ирис, расскажи",
        language="ru",
        expected_generation=generation,
    )
    await service.playback_segment_finished(
        "session",
        "Начало ответа.",
        observation.utterance_id,
        generation,
    )

    await service.speech_started("session")

    messages, _ = store.list_messages(20)
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "Начало ответа."
    assert messages[-1].status == "interrupted"


@pytest.mark.anyio
async def test_visible_generated_reply_is_committed_before_next_user_turn(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "visible-generated.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    generation = await service.speech_started("session")
    observation = await service.ingest_observation(
        session_id="session",
        transcript="ирис ответь на это",
        language="ru",
        expected_generation=generation,
    )
    generated = "Это моя странная шутка про шины и босса, она была мимо."
    await service.assistant_text_generated(
        "session", observation.utterance_id, generation, generated,
    )

    await service.speech_started("session")

    messages, _ = store.list_messages(20)
    assert messages[-1].role == "assistant"
    assert messages[-1].content == generated
    assert messages[-1].status == "completed"


def test_group_speaker_estimator_is_conservative() -> None:
    estimator = SpeakerRoleEstimator()
    unknown = estimator.estimate(
        "Положи это на стол.",
        participant_mode="group",
        addressedness=0.08,
        echo=False,
    )
    addressed = estimator.estimate(
        "Ирис, что думаешь?",
        participant_mode="group",
        addressedness=1.0,
        echo=False,
    )
    assert unknown.role is SpeakerRole.UNKNOWN
    assert addressed.role is SpeakerRole.PRIMARY
    assert "direct_address" in addressed.reasons


@pytest.mark.anyio
async def test_avatar_reaction_executes_without_assistant_turn(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    calls: list[tuple[str, str, int]] = []
    service = LiveConversationService(
        store,
        runtime(live_conversation_participant_mode="group"),
    )

    async def avatar(session_id: str, emotion: str, _intensity: float, generation: int) -> None:
        calls.append((session_id, emotion, generation))

    service.bind_action_handlers(avatar_reaction=avatar)
    generation = await service.speech_started("session")
    result = await service.ingest_observation(
        session_id="session",
        transcript="Сегодня будет дождь?",
        language="ru",
        expected_generation=generation,
    )
    assert result.decision.action is ConversationAction.AVATAR_REACTION
    assert calls == [("session", result.decision.reaction_emotion, generation)]
    messages, _ = store.list_messages(20)
    assert [message.role for message in messages] == ["user"]


@pytest.mark.anyio
async def test_deferred_reaction_is_cancelled_by_new_generation(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime())
    generation = await service.speech_started("session")
    result = await service.ingest_observation(
        session_id="session",
        transcript="Меня сегодня уволили, я просто думаю вслух.",
        language="ru",
        expected_generation=generation,
    )
    assert result.decision.action is ConversationAction.DEFER
    assert len(service.session("session").deferred_reactions) == 1
    await service.speech_started("session")
    assert len(service.session("session").deferred_reactions) == 0
    assert service.debug("session")["active_tasks"] == []


class _AdjudicationProvider:
    async def generate(self, _messages):
        return LLMResponse(
            model="fake",
            content=json.dumps(
                {
                    "version": 1,
                    "decision": {
                        "version": 1,
                        "action": "observe",
                        "reason": "ambient_speech",
                        "confidence": 0.8,
                        "addressedness": 0.1,
                        "relevance": 0.3,
                        "significance": 0.2,
                        "reaction_emotion": "neutral",
                        "defer_for_ms": None,
                        "expires_in_ms": None,
                    },
                    "appraisal": {
                        "version": 1,
                        "event_kind": "neutral",
                        "target_participant": "primary",
                        "confidence": 0.8,
                        "intensity": 0.1,
                        "valence": 0.0,
                        "arousal": 0.0,
                        "emotion_impulses": {},
                        "relationship_impulses": {},
                        "cause_message_ids": [],
                    },
                }
            ),
        )


@pytest.mark.anyio
async def test_ambiguous_observation_uses_structured_adjudicator(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(
        store,
        runtime(live_conversation_participant_mode="group"),
        llm_provider=_AdjudicationProvider(),
    )
    generation = await service.speech_started("session")
    result = await service.ingest_observation(
        session_id="session",
        transcript="Наверное, завтра будет дождь.",
        language="ru",
        expected_generation=generation,
    )
    assert result.decision.action is ConversationAction.OBSERVE
    assert service.debug("session")["last_decision_source"] == "llm"


@pytest.mark.anyio
async def test_installed_smart_turn_model_matches_synthetic_manifest() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "live_audio"
    manifest = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Settings().app_data_path)))
    model_path = ModelManager(local_app_data / "NeuroAsist" / "models").path_for("smart-turn-v3.2")
    if not model_path.is_file():
        pytest.skip("Smart Turn model is not installed")
    detector = SmartTurnDetector(model_path)
    assert detector.ready, detector.error
    for fixture in manifest["fixtures"]:
        with wave.open(str(fixture_root / fixture["file"]), "rb") as source:
            result = await detector.analyze(source.readframes(source.getnframes()), source.getframerate())
        assert result.fallback is False
        assert result.complete is fixture["expected_complete"], fixture["id"]
        assert result.latency_ms < 250


class _SlowAdjudicationProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def generate(self, _messages):
        self.started.set()
        await asyncio.sleep(30)
        raise AssertionError("stale adjudication must be cancelled")


@pytest.mark.anyio
async def test_new_speech_cancels_registered_decision_task(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    provider = _SlowAdjudicationProvider()
    service = LiveConversationService(
        store,
        runtime(live_conversation_participant_mode="group"),
        llm_provider=provider,
    )
    generation = await service.speech_started("session")
    ingest = asyncio.create_task(
        service.ingest_observation(
            session_id="session",
            transcript="Наверное, завтра будет дождь.",
            language="ru",
            expected_generation=generation,
        )
    )
    await provider.started.wait()
    assert service.debug("session")["active_tasks"][0]["reason"] == "ambiguous_observation"
    await service.speech_started("session")
    with pytest.raises(asyncio.CancelledError):
        await ingest
    assert service.debug("session")["active_tasks"] == []
    assert len(store.recent_conversation_observations("session")) == 1
