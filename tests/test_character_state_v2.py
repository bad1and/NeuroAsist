from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from apps.backend.app.conversation.schemas import EventAppraisal, SpeakerRole
from apps.backend.app.conversation.state_service import CharacterStateService
from apps.backend.app.llm.base import LLMProvider, LLMResponse
from apps.backend.app.storage.timeline import TimelineStore


class ReflectionProvider(LLMProvider):
    async def generate(self, _messages):
        return LLMResponse(
            content='{"text":"Я рада, что мы справились с важным делом вместе. Мне хочется сохранить ощущение общего успеха."}',
            model="reflection-test",
        )


def test_state_transition_is_atomic_idempotent_and_persistent(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store, reflection_llm_provider=ReflectionProvider())

    insult = EventAppraisal(
        event_kind="insult", confidence=0.85, intensity=0.7, valence=-0.75, arousal=0.75,
        direction="toward_iris", emotion_impulses={"hurt": 0.7, "irritation": 0.45},
        relationship_impulses={"trust": -0.35, "tension": 0.5}, cause_message_ids=["message-1"],
    )
    first = service.prepare(transcript="Ты тупая", message_id="message-1", appraisal=insult)
    retry = service.prepare(transcript="Ты тупая", message_id="message-1", appraisal=insult)

    assert first.state_applied is True
    assert retry.state_applied is False
    assert first.event_id == retry.event_id
    assert first.affect.hurt > 0
    assert first.behavior.closeness_policy in {"reserved", "distant"}
    assert "нерешённую причину" in first.prompt_block()

    snapshot = store.load_character_state_snapshot("primary")
    assert snapshot is not None and snapshot["schema_version"] == 2
    restored = CharacterStateService(store).current()
    assert restored.affect.hurt > 0
    assert restored.relationship.tension > 0


def test_ambient_and_uncertain_speech_does_not_change_primary_state(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    ambient = service.prepare(
        transcript="Ты тупая", message_id="ambient-1", speaker_role=SpeakerRole.OTHER,
    )
    uncertain = service.prepare(
        transcript="Ты тупая", message_id="uncertain-1", stt_uncertain=True,
    )

    assert ambient.state_applied is False
    assert uncertain.state_applied is False
    assert service.current().affect.hurt == 0


def test_apology_repairs_but_does_not_erase_negative_cause(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    insult_appraisal = EventAppraisal(
        event_kind="insult", confidence=0.85, intensity=0.7, valence=-0.75, arousal=0.75,
        direction="toward_iris", emotion_impulses={"hurt": 0.7, "irritation": 0.45},
        relationship_impulses={"trust": -0.35, "tension": 0.5}, cause_message_ids=["insult"],
    )
    apology_appraisal = EventAppraisal(
        event_kind="apology", confidence=0.85, intensity=0.7, valence=0.7, arousal=0.5,
        direction="toward_iris", emotion_impulses={"hurt": -0.85, "irritation": -0.65},
        relationship_impulses={"tension": -0.55, "warmth": 0.25}, cause_message_ids=["apology"],
    )
    insult = service.prepare(transcript="Ты тупая", message_id="insult", appraisal=insult_appraisal)
    apology = service.prepare(transcript="Прости, я был неправ", message_id="apology", appraisal=apology_appraisal)

    assert apology.affect.hurt < insult.affect.hurt
    assert apology.affect.active_cause_labels
    assert apology.relationship.tension < insult.relationship.tension


def test_only_significant_events_create_isolated_reflections(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store, reflection_llm_provider=ReflectionProvider())
    service.prepare(transcript="Привет", message_id="neutral")
    assert store.list_reflections("primary") == []
    success_appraisal = EventAppraisal(
        event_kind="shared_success", confidence=0.85, intensity=0.6, valence=0.55,
        direction="toward_iris", emotion_impulses={"joy": 0.55}, cause_message_ids=["success"],
    )
    service.prepare(transcript="Мы закончили, получилось! " + "важно " * 30, message_id="success", appraisal=success_appraisal)
    assert asyncio.run(service.run_reflection_once()) is True
    reflections = store.list_reflections("primary")
    assert len(reflections) == 1
    assert "справились" in str(reflections[0]["text"])
    assert store.delete_reflection(str(reflections[0]["id"])) is True
    assert store.list_reflections("primary") == []


def test_v1_snapshot_adapts_and_disabled_reflection_never_queues(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    store.save_character_state_snapshot("primary", {"hurt": .4, "updated_at": "2026-01-01T00:00:00+00:00"}, schema_version=1)
    service = CharacterStateService(store, reflection_policy=lambda: (False, .3))

    restored = service.current()
    assert restored.affect.schema_version == 2
    service.prepare(transcript="Мы закончили, получилось! " + "важно " * 30, message_id="disabled")
    assert asyncio.run(service.run_reflection_once()) is False
    assert store.list_reflections("primary") == []


def test_reflection_causal_window_loads_off_the_event_loop(monkeypatch, tmp_path: Path) -> None:
    """The worker reads its prompt material in a thread, not on the loop.

    A live turn schedules audio on this same loop, and the read block used to
    hold it for about 9 ms. It must also complete over one pinned connection.
    """
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    for index in range(8):
        store.append_message(
            role="user" if index % 2 == 0 else "assistant",
            content=f"реплика {index} " + "несколько слов для контекста " * 10,
            input_mode="text",
        )
    trigger, _ = store.append_message(
        role="user",
        content="Мы закончили, получилось! " + "важно " * 30,
        input_mode="text",
    )
    service = CharacterStateService(
        store,
        reflection_llm_provider=ReflectionProvider(),
        event_publisher=lambda *_args, **_kwargs: None,
    )
    success_appraisal = EventAppraisal(
        event_kind="shared_success", confidence=0.85, intensity=0.6, valence=0.55,
        direction="toward_iris", emotion_impulses={"joy": 0.55}, cause_message_ids=[str(trigger.id)],
    )
    service.prepare(transcript="Мы закончили, получилось! " + "важно " * 30, message_id=str(trigger.id), appraisal=success_appraisal)

    calls: list[tuple[int, str]] = []
    for target in (
        store.get_message,
        store.load_character_state_snapshot,
        store.load_participant_states,
    ):
        name = getattr(target, "__name__", "?")
        monkeypatch.setattr(
            store, name,
            (lambda wrapped: lambda *args, **kwargs: (
                calls.append((threading.get_ident(), name)),
                wrapped(*args, **kwargs),
            )[1])(target),
        )

    loop_tid = threading.get_ident()
    asyncio.run(service.run_reflection_once())

    assert calls, "the worker must read the prompt material"
    assert all(tid != loop_tid for tid, _ in calls), "reads must happen off the event loop"
    assert store.list_reflections("primary")


def test_apology_variations_repair_and_assistant_forgiveness_clears_hurt(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    # 1. AI model responded with annoyance to an insult
    service.record_assistant_turn(
        reply_text="Не разговаривай со мной в таком тоне.",
        emotion="annoyed",
        intensity=0.8,
    )
    annoyed_state = service.current()
    assert annoyed_state.affect.primary_emotion == "irritation"

    # 2. When user apologizes, AI model responds with warmth and forgiveness
    service.record_assistant_turn(
        reply_text="Ладно, проехали! Я тебя прощаю, всё нормально :)",
        emotion="happy",
        intensity=0.75,
    )

    # 3. State is completely forgiven and joyful
    restored = service.current()
    assert restored.affect.hurt == 0.0
    assert restored.affect.primary_emotion == "joy"
    assert len(restored.affect.active_cause_labels) == 0


def test_casual_swearing_is_external_and_does_not_offend_iris(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    # User message contains swearing, but because keywords are removed, it stays neutral
    vent = service.prepare(transcript="Блядь, пиздец на улице холодно, заебало", message_id="msg-vent-1")
    assert vent.appraisal.event_kind == "neutral"
    current = service.current()
    assert current.affect.hurt == 0.0
    assert current.affect.primary_emotion == "neutral"


def test_playful_teasing_does_not_cause_insult_hurt(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    # Friendly banter / teasing controlled directly by AI response
    service.record_assistant_turn(
        reply_text="Ха-ха, ну ты сам тот ещё фрукт!",
        emotion="smirk",
        intensity=0.8,
    )
    current = service.current()
    assert current.affect.primary_emotion == "playfulness"
    assert current.affect.playfulness > 0
    assert current.affect.hurt == 0.0

