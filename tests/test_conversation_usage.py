import asyncio
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.backend.app.api.routes.conversation import router
from apps.backend.app.conversation.turn_coordinator import ConversationTurnCoordinator
from apps.backend.app.conversation.usage import ConversationUsageTracker
from apps.backend.app.conversation.service import LiveConversationService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore, LATEST_SCHEMA_VERSION


@pytest.fixture
def usage(tmp_path):
    store = TimelineStore(tmp_path / "usage.sqlite3")
    store.init_db()
    clock = [1000.0]
    tracker = ConversationUsageTracker(store, clock=lambda: clock[0])
    tracker.start()
    return store, tracker, clock


def test_active_intervals_are_unioned_and_stop_after_five_minutes(usage):
    _, tracker, clock = usage
    clock[0] += 100
    assert tracker.snapshot()["active_seconds"] == 0
    tracker.record_activity("text:user")
    clock[0] += 30
    tracker.record_activity("voice:user")
    clock[0] += 20
    tracker.record_activity("voice:assistant")
    clock[0] += 500
    assert tracker.snapshot()["active_seconds"] == 350
    tracker.record_activity("new:turn")
    clock[0] += 12
    assert tracker.snapshot()["active_seconds"] == 362


def test_duplicate_delivery_does_not_extend_idle_interval(usage):
    _, tracker, clock = usage
    tracker.record_activity("same:turn")
    clock[0] += 290
    tracker.record_activity("same:turn")
    clock[0] += 50
    assert tracker.snapshot()["active_seconds"] == 300


def test_incognito_stops_counting_and_requires_new_activity_on_exit(usage):
    _, tracker, clock = usage
    tracker.record_activity("public")
    clock[0] += 20
    tracker.set_paused(True)
    tracker.record_activity("private")
    clock[0] += 500
    tracker.set_paused(False)
    clock[0] += 100
    assert tracker.snapshot()["active_seconds"] == 20
    tracker.record_activity("public:again")
    clock[0] += 10
    assert tracker.snapshot()["active_seconds"] == 30


def test_checkpoint_and_restart_do_not_count_offline_time(usage):
    store, tracker, clock = usage
    tracker.record_activity("before:crash")
    clock[0] += 15
    tracker.checkpoint()
    clock[0] += 9999
    restored = ConversationUsageTracker(store, clock=lambda: clock[0])
    restored.start()
    assert restored.snapshot()["active_seconds"] == 15
    assert restored.snapshot()["tracking_started_at"] == tracker.snapshot()["tracking_started_at"]
    restored.record_activity("after:restart")
    clock[0] += 7
    restored.close()
    assert store.conversation_usage()["active_seconds"] == 22
    clock[0] += 100
    assert restored.snapshot()["active_seconds"] == 22


def test_v22_migration_preserves_history_and_does_not_backfill_time(tmp_path):
    path = tmp_path / "old.sqlite3"
    store = TimelineStore(path)
    store.init_db()
    message, _ = store.append_message(role="user", content="Старая история", input_mode="text")
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 22")
        connection.execute("DROP TABLE conversation_usage")
    store.init_db()
    assert store.get_message(message.id).content == "Старая история"
    assert store.conversation_usage()["active_seconds"] == 0
    started = store.conversation_usage()["tracking_started_at"]
    store.init_db()
    assert store.conversation_usage()["tracking_started_at"] == started
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == LATEST_SCHEMA_VERSION
    assert (tmp_path / "migration-backups" / "old-schema-21.sqlite3").exists()


def test_usage_endpoint_is_content_free_and_unavailable_without_tracker(usage):
    _, tracker, clock = usage
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/conversation/usage").status_code == 503
    app.state.conversation_usage = tracker
    tracker.record_activity("turn")
    clock[0] += 24
    body = client.get("/conversation/usage").json()
    assert set(body) == {"active_seconds", "tracking_started_at"}
    assert body["active_seconds"] == 24


def test_coordinator_records_new_text_voice_and_completed_replies_once(usage):
    store, tracker, clock = usage
    calls = []

    def record(event_id):
        calls.append(event_id)
        tracker.record_activity(event_id)

    async def scenario():
        coordinator = ConversationTurnCoordinator(store, activity_recorder=record)
        first = await coordinator.accept_user_turn(session_id="chat", content="Привет", input_mode="text", client_message_id="one")
        clock[0] += 10
        await coordinator.accept_user_turn(session_id="chat", content="Привет", input_mode="text", client_message_id="one")
        lease = await coordinator.begin_assistant(first)
        await coordinator.complete_assistant("chat", lease, "Здравствуй")
        await coordinator.complete_assistant("chat", lease, "Здравствуй")
        clock[0] += 20
        await coordinator.accept_user_turn(session_id="chat", content="Голос", input_mode="voice")

    asyncio.run(scenario())
    assert len(set(calls)) == 3
    assert tracker.snapshot()["active_seconds"] == 30


def test_live_voice_counts_addressed_turns_and_played_replies_not_ambient_speech(usage):
    store, tracker, clock = usage
    runtime = RuntimeSettings()
    calls = []

    def record(event_id):
        calls.append(event_id)
        tracker.record_activity(event_id)

    async def scenario():
        service = LiveConversationService(store, runtime, activity_recorder=record)
        generation = await service.speech_started("voice")
        await service.ingest_observation(session_id="voice", transcript="Я просто думаю вслух.", language="ru", expected_generation=generation)
        assert calls == []
        generation = await service.speech_started("voice")
        result = await service.ingest_observation(session_id="voice", transcript="Ирис, помоги мне выбрать книгу.", language="ru", expected_generation=generation)
        assert len(calls) == 1
        clock[0] += 9
        await service.assistant_text_generated("voice", result.utterance_id, generation, "Давай подберём книгу.")
        await service.playback_finished("voice", result.utterance_id)
        await service.playback_finished("voice", result.utterance_id)
        assert len(calls) == 2
        runtime.memory_incognito = True
        generation = await service.speech_started("voice")
        await service.ingest_observation(session_id="voice", transcript="Ирис, расскажи ещё что-нибудь.", language="ru", expected_generation=generation)
        assert len(calls) == 2
        await service.close()

    asyncio.run(scenario())
    assert tracker.snapshot()["active_seconds"] == 9
