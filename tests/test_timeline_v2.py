import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from apps.backend import main as backend_main
from apps.backend.app.api.routes import chat as chat_route
from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import LLMResponse


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
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,), (2,), (3,), (4,), (5,)]
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
