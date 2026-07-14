from pathlib import Path

from fastapi.testclient import TestClient

from apps.backend import main as backend_main
from apps.backend.app.core.config import Settings
from apps.backend.app.storage.timeline import EpisodePolicy, TimelineStore


def make_store(tmp_path: Path, **policy_values: int) -> tuple[TimelineStore, list[tuple[str, dict]]]:
    events: list[tuple[str, dict]] = []
    policy = EpisodePolicy(**policy_values)
    store = TimelineStore(
        tmp_path / "episodes.sqlite3",
        policy,
        lambda event_type, _level, _message, metadata: events.append((event_type, metadata)),
    )
    store.init_db()
    return store, events


def test_short_pause_continues_and_long_pause_starts_new_episode(tmp_path: Path) -> None:
    store, events = make_store(tmp_path, hard_inactivity_seconds=60, soft_inactivity_seconds=20)
    first, _ = store.append_message(role="user", content="Начинаем", input_mode="text", created_at="2026-07-14T10:00:00+00:00")
    second, _ = store.append_message(role="assistant", content="Продолжаем", input_mode="text", created_at="2026-07-14T10:00:10+00:00")
    third, _ = store.append_message(role="user", content="Вернулся", input_mode="text", created_at="2026-07-14T10:02:00+00:00")

    episodes = store.list_episodes()
    assert first.episode_id == second.episode_id
    assert third.episode_id != first.episode_id
    assert episodes[1]["boundary_reason"] == "inactivity"
    assert episodes[1]["message_count"] == 2
    assert episodes[0]["status"] == "active"
    assert [event for event, _ in events].count("episode.started") == 2
    assert any(event == "episode.closed" and metadata["boundary_reason"] == "inactivity" for event, metadata in events)


def test_calendar_boundary_and_context_pressure_do_not_create_empty_episodes(tmp_path: Path) -> None:
    store, _ = make_store(tmp_path, hard_inactivity_seconds=3600, soft_inactivity_seconds=60, maximum_messages=2)
    first, _ = store.append_message(role="user", content="Поздно", input_mode="text", created_at="2026-07-14T23:50:00+00:00")
    second, _ = store.append_message(role="assistant", content="Уже завтра", input_mode="text", created_at="2026-07-15T00:10:00+00:00")
    third, _ = store.append_message(role="user", content="Ещё один turn", input_mode="text", created_at="2026-07-15T00:10:01+00:00")
    fourth, _ = store.append_message(role="assistant", content="Новый pressure episode", input_mode="text", created_at="2026-07-15T00:10:02+00:00")

    episodes = store.list_episodes()
    assert first.episode_id != second.episode_id
    assert second.episode_id == third.episode_id
    assert fourth.episode_id != second.episode_id
    assert {episode["boundary_reason"] for episode in episodes if episode["boundary_reason"]} == {"calendar_boundary", "context_pressure"}
    assert all(episode["message_count"] > 0 for episode in episodes)


def test_manual_close_and_restart_recovery_wait_for_real_next_message(tmp_path: Path) -> None:
    store, _ = make_store(tmp_path, hard_inactivity_seconds=60, soft_inactivity_seconds=20)
    first, _ = store.append_message(role="user", content="Закроем", input_mode="text", created_at="2026-07-14T10:00:00+00:00")
    manually_closed = store.close_current_episode(now="2026-07-14T10:00:01+00:00")

    assert manually_closed is not None
    assert manually_closed["boundary_reason"] == "manual_reset"
    assert store.current_episode() is None
    assert len(store.list_episodes()) == 1

    second, _ = store.append_message(role="user", content="Новый разговор", input_mode="text", created_at="2026-07-14T10:00:02+00:00")
    recovered = store.recover_active_episode(now="2026-07-14T10:02:00+00:00")

    assert second.episode_id != first.episode_id
    assert recovered is not None
    assert recovered["boundary_reason"] == "application_restart"
    assert store.current_episode() is None
    assert len(store.list_episodes()) == 2


def test_episode_api_exposes_internal_groups_and_manual_close(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "api.sqlite3"),
        timeline_v2_enabled=True,
        episodes_enabled=True,
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)
    with TestClient(backend_main.create_app()) as client:
        assert client.get("/episodes").json() == {"items": []}
        created = client.post("/timeline/messages", json={"role": "user", "content": "Создай episode"})
        episode_id = created.json()["message"]["episode_id"]
        fetched = client.get(f"/episodes/{episode_id}")
        closed = client.post("/episodes/current/close")
        no_current = client.post("/episodes/current/close")

    assert fetched.json()["episode"]["status"] == "active"
    assert closed.json()["episode"]["boundary_reason"] == "manual_reset"
    assert no_current.status_code == 409
