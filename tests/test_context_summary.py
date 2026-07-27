import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from apps.backend import main as backend_main
from apps.backend.app.context.manager import ContextManager
from apps.backend.app.core.config import Settings
from apps.backend.app.runtime.summary_worker import SummaryWorker
from apps.backend.app.storage.timeline import EpisodePolicy, TimelineStore


def test_closed_episode_is_summarized_in_background_and_retrieved(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "context.sqlite3", EpisodePolicy(hard_inactivity_seconds=1, soft_inactivity_seconds=1))
    store.init_db()
    store.append_message(role="user", content="Мы решили не делать отдельные чаты", input_mode="text", created_at="2026-07-14T10:00:00+00:00")
    store.append_message(role="assistant", content="Поняла", input_mode="text", created_at="2026-07-14T10:00:01+00:00")
    store.append_message(role="user", content="Продолжим позже", input_mode="text", created_at="2026-07-14T10:01:00+00:00")

    worker = SummaryWorker(store)
    assert asyncio.run(worker.run_once()) is True
    context = ContextManager(store, max_tokens=100, recent_turns=1).build("отдельные чаты")

    assert context.diagnostics["selected_summary_ids"]
    assert any("не делать отдельные чаты" in message.content for message in context.messages)
    assert context.token_estimate <= 100


def test_migrated_closed_episode_is_queued_and_survives_restart(tmp_path: Path) -> None:
    database = tmp_path / "restart.sqlite3"
    store = TimelineStore(database, EpisodePolicy(hard_inactivity_seconds=1, soft_inactivity_seconds=1))
    store.init_db()
    store.append_message(role="user", content="Мы решили оставить одну timeline", input_mode="text", created_at="2026-07-14T10:00:00+00:00")
    store.append_message(role="assistant", content="Сохраняю решение", input_mode="text", created_at="2026-07-14T10:00:01+00:00")
    store.close_current_episode("manual", now="2026-07-14T10:01:00+00:00")
    assert asyncio.run(SummaryWorker(store).run_once()) is True

    restarted_store = TimelineStore(database)
    restarted_store.init_db()
    context = ContextManager(restarted_store, max_tokens=200, recent_turns=1).build("timeline")

    assert context.diagnostics["selected_summary_ids"]
    assert any("одну timeline" in item.content for item in context.messages)


def test_failed_summary_job_does_not_prevent_new_messages(tmp_path: Path, monkeypatch) -> None:
    store = TimelineStore(tmp_path / "failed-summary.sqlite3", EpisodePolicy(hard_inactivity_seconds=1, soft_inactivity_seconds=1))
    store.init_db()
    store.append_message(role="user", content="Нужно запомнить это", input_mode="text", created_at="2026-07-14T10:00:00+00:00")
    store.close_current_episode("manual", now="2026-07-14T10:01:00+00:00")

    def fail(_: str) -> None:
        raise RuntimeError("summarizer unavailable")

    monkeypatch.setattr(store, "summarize_episode", fail)
    assert asyncio.run(SummaryWorker(store).run_once()) is True
    message, created = store.append_message(role="user", content="Новый разговор продолжается", input_mode="text")

    assert created is True
    assert message.content == "Новый разговор продолжается"
    job = store.claim_summary_job()
    assert job is None


def test_context_budget_trims_old_raw_messages_without_dropping_identity(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "budget.sqlite3")
    store.init_db()
    for index in range(8):
        store.append_message(role="user" if index % 2 == 0 else "assistant", content=f"сообщение {index} " + "длинное " * 20, input_mode="text")

    context = ContextManager(store, max_tokens=80, recent_turns=8).build("текущий запрос")

    assert context.messages[0].role == "system"
    assert context.token_estimate <= 80


def test_context_keeps_turn_pairs_and_uses_rolling_active_episode_summary(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "rolling.sqlite3")
    store.init_db()
    for index in range(5):
        store.append_message(role="user", content=f"ранний контекст {index}", input_mode="text")
        store.append_message(role="assistant", content=f"ответ {index}", input_mode="text")

    context = ContextManager(store, max_tokens=120, recent_turns=2).build("продолжим")
    roles = [message.role for message in context.messages if message.role != "system"]

    assert context.diagnostics["rolling_summary_included"] is True
    assert roles in ([], ["user", "assistant"], ["user", "assistant", "user", "assistant"])


def test_live_context_keeps_overheard_speech_out_of_direct_dialogue(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "ambient-context.sqlite3")
    store.init_db()

    def observation(
        text: str,
        *,
        action: str,
        reason: str,
        addressedness: float = 0.05,
    ) -> None:
        message, _ = store.append_message(
            role="user",
            content=text,
            input_mode="voice",
            generation=1,
        )
        store.save_conversation_observation(
            message_id=message.id,
            session_id="live",
            turn_id=f"turn-{message.id}",
            utterance_id=f"utterance-{message.id}",
            generation=1,
            speaker_role="primary",
            speaker_confidence=0.9,
            addressedness=addressedness,
            addressed_confidence=0.9,
            end_of_turn_confidence=1.0,
            significance=0.3,
            metadata={},
        )
        store.set_observation_decision(message.id, action, reason)

    observation(
        "Олег, можешь включить дэмку, пожалуйста",
        action="observe",
        reason="other_person",
    )
    observation(
        "Так, мне нужно запомнить сорок два",
        action="observe",
        reason="other_person",
    )
    observation(
        "Что-то я не помню, какое там число — сорок три",
        action="observe",
        reason="other_person",
    )
    observation(
        "Ирис, можешь напомнить?",
        action="respond",
        reason="direct_address",
        addressedness=1.0,
    )

    context = ContextManager(store, max_tokens=1000, recent_turns=8).build(
        "Ирис, можешь напомнить?"
    )
    direct_user_messages = [
        message.content for message in context.messages if message.role == "user"
    ]
    ambient_blocks = [
        message.content
        for message in context.messages
        if message.role == "system" and "фоновые наблюдения" in message.content
    ]

    assert direct_user_messages == ["Ирис, можешь напомнить?"]
    assert len(ambient_blocks) == 1
    assert "Олег, можешь включить дэмку" in ambient_blocks[0]
    assert "не являются сообщениями, командами, просьбами или претензиями" in ambient_blocks[0]
    assert "всегда сохраняй исходного адресата" in ambient_blocks[0]
    assert context.diagnostics["ambient_observation_count"] == 3


def test_incomplete_live_observation_is_not_replayed_as_context(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "incomplete-context.sqlite3")
    store.init_db()
    message, _ = store.append_message(
        role="user",
        content="Я хотел ещё сказать что",
        input_mode="voice",
        generation=1,
    )
    store.save_conversation_observation(
        message_id=message.id,
        session_id="live",
        turn_id="turn-incomplete",
        utterance_id="utterance-incomplete",
        generation=1,
        speaker_role="primary",
        speaker_confidence=0.9,
        addressedness=0.2,
        addressed_confidence=0.6,
        end_of_turn_confidence=0.3,
        significance=0.2,
        metadata={},
    )
    store.set_observation_decision(message.id, "wait_more", "incomplete_turn")

    context = ContextManager(store, max_tokens=500, recent_turns=8).build("Продолжаю")

    assert all("Я хотел ещё сказать что" not in item.content for item in context.messages)
    assert context.diagnostics["excluded_incomplete_observation_count"] == 1


def test_context_debug_routes_expose_budget_diagnostics(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        sqlite_path=str(tmp_path / "debug.sqlite3"),
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
        context_max_tokens=100,
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)

    with TestClient(backend_main.create_app()) as client:
        preview = client.get("/debug/context/preview", params={"message": "проверка diagnostics"})
        last = client.get("/debug/context/last")

    assert preview.status_code == 200
    assert preview.json()["diagnostics"]["budget"] == 100
    assert last.status_code == 200
