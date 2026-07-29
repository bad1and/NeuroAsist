import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.backend import main as backend_main
from apps.backend.app.api.routes import chat as chat_route
from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import LLMResponse
from apps.backend.app.storage.timeline import TimelineStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "v0.4.1-history.sqlite3"


def make_client(monkeypatch, tmp_path: Path) -> tuple[TestClient, Path]:
    database = tmp_path / "legacy.sqlite3"
    database.write_bytes(FIXTURE.read_bytes())
    settings = Settings(
        sqlite_path=str(database),
        log_to_file=False,
        timeline_v2_enabled=True,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)
    return TestClient(backend_main.create_app()), database


def test_v041_history_migrates_to_one_primary_timeline(monkeypatch, tmp_path: Path) -> None:
    client, database = make_client(monkeypatch, tmp_path)
    with client:
        timeline = client.get("/timeline")
        messages = client.get("/timeline/messages?limit=50")

    assert timeline.status_code == 200
    assert timeline.json()["id"] == "primary-timeline"
    assert timeline.json()["relationship"]["id"] == "primary"
    payload = messages.json()["items"]
    assert [item["content"] for item in payload] == [
        "Привет, Нейро.", "Привет! Я на связи.", "Проверим голос.", "Голосовой цикл готов.",
    ]
    assert {item["metadata"].get("legacy_session_id") for item in payload} == {"default", "voice-demo"}
    assert {item["session_id"] for item in payload} == {"default", "voice-demo"}
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [
                (1,), (2,), (3,), (4,), (5,), (6,), (10,), (11,), (12,), (13,), (14,), (15,), (16,),
        ]
        assert connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone() == (4,)
        assert connection.execute("SELECT status, message_count FROM conversation_episodes").fetchall() == [("closed", 4)]


def test_timeline_append_is_idempotent_and_preserves_correction_audit(monkeypatch, tmp_path: Path) -> None:
    client, _ = make_client(monkeypatch, tmp_path)
    with client:
        request = {"role": "user", "content": "Исправь transcription", "client_message_id": "client-1", "input_mode": "voice"}
        first = client.post("/timeline/messages", json=request)
        second = client.post("/timeline/messages", json=request)
        message_id = first.json()["message"]["id"]
        corrected = client.patch(f"/timeline/messages/{message_id}", json={"corrected_content": "Исправь транскрипцию"})
        searched = client.get("/timeline/search", params={"q": "транскрипц"})

    assert first.status_code == 200 and first.json()["created"] is True
    assert second.status_code == 200 and second.json()["created"] is False
    assert second.json()["message"]["id"] == message_id
    assert corrected.json()["message"]["content"] == "Исправь транскрипцию"
    assert corrected.json()["message"]["original_content"] == "Исправь transcription"
    assert corrected.json()["message"]["metadata"]["correction_pending_review"] is True
    assert [item["id"] for item in searched.json()["items"]] == [message_id]


def test_sequence_numbers_are_causal_when_timestamps_collide(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "causal.sqlite3")
    store.init_db()
    when = "2026-07-28T10:00:00.000+00:00"
    user, _ = store.append_message(role="user", content="первая мысль", input_mode="text", created_at=when)
    assistant, _ = store.append_message(
        role="assistant", content="ответ на первую", input_mode="text", created_at=when,
        turn_id=user.turn_id, reply_to_message_id=user.id,
    )
    assert [item.sequence_no for item in (user, assistant)] == [1, 2]
    assert assistant.turn_id == user.turn_id
    assert assistant.reply_to_message_id == user.id
    assert [item.content for item in store.get_recent_messages("default", 2)] == ["первая мысль", "ответ на первую"]


def test_session_reset_erases_dialog_but_preserves_memory_and_rejects_old_session(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "session.sqlite3")
    store.init_db()
    first = store.reset_session()["session_id"]
    message = store.accept_user_turn(session_key=str(first), content="старый диалог", input_mode="text").message
    memory = store.create_memory({
        "scope": "user_profile", "kind": "identity", "subject": "user",
        "predicate": "name", "value_text": "Роман", "source_message_ids": [message.id],
    }, actor="test")

    second = store.reset_session()["session_id"]

    assert second != first
    assert store.get_recent_messages(str(second), 10) == []
    assert store.get_memory(str(memory["id"])) is not None
    with pytest.raises(ValueError, match="no longer active"):
        store.accept_user_turn(session_key=str(first), content="устаревшая сессия", input_mode="text")


def test_session_reset_endpoint_issues_new_id_and_rejects_stale_requests(monkeypatch, tmp_path: Path) -> None:
    client, _ = make_client(monkeypatch, tmp_path)
    with client:
        first = client.post("/conversation/session/reset")
        second = client.post("/conversation/session/reset")
        stale = client.post("/chat", json={"session_id": first.json()["session_id"], "message": "устарело"})

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["session_id"] != second.json()["session_id"]
    assert stale.status_code == 409


def test_timeline_pagination_journal_and_range_deletion(monkeypatch, tmp_path: Path) -> None:
    client, _ = make_client(monkeypatch, tmp_path)
    with client:
        page = client.get("/timeline/messages?limit=2&offset=0")
        journal = client.get("/timeline/journal")
        rejected = client.delete("/timeline/range")
        deleted = client.delete("/timeline/range?before=2026-07-13T23:59:59.999Z")
        remaining = client.get("/timeline/messages?limit=50")

    assert len(page.json()["items"]) == 2
    assert page.json()["next_offset"] == 2
    assert journal.json()["items"][0]["message_count"] == 4
    assert rejected.status_code == 422
    assert deleted.json() == {"deleted": 4}
    assert remaining.json()["items"] == []


def test_timeline_search_accepts_hyphenated_russian_text(monkeypatch, tmp_path: Path) -> None:
    client, _ = make_client(monkeypatch, tmp_path)
    with client:
        created = client.post(
            "/timeline/messages",
            json={
                "role": "user",
                "content": "Давай обсудим какую-нибудь тему.",
                "client_message_id": "hyphenated-search",
            },
        )
        searched = client.get("/timeline/search", params={"q": "какую-нибудь"})

    assert created.status_code == 200
    assert searched.status_code == 200
    assert any(item["content"] == "Давай обсудим какую-нибудь тему." for item in searched.json()["items"])


def test_legacy_chat_contract_writes_to_primary_timeline(monkeypatch, tmp_path: Path) -> None:
    class SuccessfulProvider:
        def __init__(self, settings, model=None) -> None:
            self.model = model

        async def generate(self, messages):
            return LLMResponse(content='{"reply":"Одна история","emotion":"neutral","intent":"casual_chat"}', model="test")

    monkeypatch.setattr(chat_route, "DeepSeekProvider", SuccessfulProvider)
    client, _ = make_client(monkeypatch, tmp_path)
    with client:
        response = client.post("/chat", json={"session_id": "old-session-name", "message": "Продолжим"})
        messages = client.get("/timeline/messages?limit=50").json()["items"]

    assert response.status_code == 200
    appended = messages[-2:]
    assert [(item["role"], item["content"]) for item in appended] == [
        ("user", "Продолжим"), ("assistant", "Одна история"),
    ]
    assert {item["metadata"]["legacy_session_id"] for item in appended} == {"old-session-name"}
