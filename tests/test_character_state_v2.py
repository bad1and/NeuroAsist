from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from apps.backend.app.conversation.schemas import SpeakerRole
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

    first = service.prepare(transcript="Ты тупая", message_id="message-1")
    retry = service.prepare(transcript="Ты тупая", message_id="message-1")

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

    insult = service.prepare(transcript="Ты тупая", message_id="insult")
    apology = service.prepare(transcript="Прости, я был неправ", message_id="apology")

    assert apology.affect.hurt < insult.affect.hurt
    assert apology.affect.active_cause_labels
    assert apology.relationship.tension < insult.relationship.tension


def test_only_significant_events_create_isolated_reflections(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store, reflection_llm_provider=ReflectionProvider())
    service.prepare(transcript="Привет", message_id="neutral")
    assert store.list_reflections("primary") == []
    service.prepare(transcript="Мы закончили, получилось! " + "важно " * 30, message_id="success")
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
    service.prepare(transcript="Мы закончили, получилось! " + "важно " * 30, message_id=str(trigger.id))

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
