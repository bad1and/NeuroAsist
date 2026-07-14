from pathlib import Path
import asyncio
import logging
import time

from fastapi.testclient import TestClient
import pytest

from apps.backend.app.api.routes import voice as voice_route
from apps.backend.app.llm.base import LLMProviderError, LLMResponse
from apps.backend.app.voice.providers import MockTTSProvider
from apps.backend.app.voice.service import VoiceService
from apps.backend.main import app


class SuccessfulLLMProvider:
    def __init__(self, settings, model=None):
        self.settings = settings
        self.model = model

    async def generate(self, messages):
        return LLMResponse(
            content='{"reply":"Голос услышан","emotion":"happy","intent":"casual_chat"}',
            model=self.model or "test-model",
        )


class FailingLLMProvider:
    def __init__(self, settings, model=None):
        self.settings = settings
        self.model = model

    async def generate(self, messages):
        raise LLMProviderError("provider failed")


class FailingTTSProvider:
    async def synthesize(self, text, voice, output_path):
        raise RuntimeError("tts failed")


class SlowTTSProvider:
    async def synthesize(self, text, voice, output_path):
        await asyncio.sleep(0.5)
        return await MockTTSProvider().synthesize(text, voice, output_path)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    settings = app.state.settings
    original_stt = settings.voice_stt_provider
    original_tts = settings.voice_tts_provider
    original_audio_dir = settings.voice_audio_dir
    original_tts_enabled = settings.voice_tts_enabled
    original_tts_timeout = settings.voice_tts_background_timeout_seconds
    original_service = app.state.voice_service
    settings.voice_stt_provider = "mock"
    settings.voice_tts_provider = "mock"
    settings.voice_tts_enabled = True
    settings.voice_tts_background_timeout_seconds = 2
    settings.voice_audio_dir = str(tmp_path / "audio")
    app.state.voice_service = VoiceService(settings)
    monkeypatch.setattr(voice_route, "DeepSeekProvider", SuccessfulLLMProvider)

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.state.voice_service.clear_audio_dir()
        settings.voice_stt_provider = original_stt
        settings.voice_tts_provider = original_tts
        settings.voice_audio_dir = original_audio_dir
        settings.voice_tts_enabled = original_tts_enabled
        settings.voice_tts_background_timeout_seconds = original_tts_timeout
        app.state.voice_service = original_service


def wait_for_event(client: TestClient, session_id: str, event_type: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        events = client.get("/events?limit=100").json()["events"]
        for event in reversed(events):
            if (
                event["type"] == event_type
                and event["metadata"].get("session_id") == session_id
            ):
                return event
        time.sleep(0.05)
    raise AssertionError(f"Event not found: {event_type}")


def test_voice_chat_returns_transcript_reply_and_queues_tts(client: TestClient) -> None:
    response = client.post(
        "/voice/chat",
        data={"session_id": "voice-success", "language": "ru"},
        files={"audio": ("voice.webm", b"fake audio", "audio/webm")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "Тестовое голосовое сообщение"
    assert body["reply"] == "Голос услышан"
    assert body["emotion"] == "happy"
    assert body["intent"] == "casual_chat"
    assert body["voice_request_id"]
    assert body["reply_audio_url"] is None
    assert body["tts_status"] == "queued"
    assert body["stt"]["provider"] == "mock"
    assert body["tts"]["provider"] == "mock"
    assert body["tts"]["voice"] == "xenia"
    assert body["tts"]["duration_ms"] == 0
    assert body["memory_updates"] == []


def test_voice_chat_rejects_unsupported_audio_type(client: TestClient) -> None:
    response = client.post(
        "/voice/chat",
        data={"session_id": "voice-bad-type", "language": "ru"},
        files={"audio": ("voice.txt", b"fake audio", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported audio type"


def test_voice_chat_accepts_webm_with_codec_parameter(client: TestClient) -> None:
    response = client.post(
        "/voice/chat",
        data={"session_id": "voice-webm-codec", "language": "ru"},
        files={"audio": ("voice.webm", b"fake audio", "audio/webm;codecs=opus")},
    )

    assert response.status_code == 200
    assert response.json()["transcript"] == "Тестовое голосовое сообщение"


def test_voice_chat_accepts_octet_stream_with_audio_extension(client: TestClient) -> None:
    response = client.post(
        "/voice/chat",
        data={"session_id": "voice-octet-stream", "language": "ru"},
        files={"audio": ("voice.webm", b"fake audio", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json()["transcript"] == "Тестовое голосовое сообщение"


def test_voice_chat_publishes_voice_events(client: TestClient) -> None:
    session_id = "voice-events"

    response = client.post(
        "/voice/chat",
        data={"session_id": session_id, "language": "ru"},
        files={"audio": ("voice.webm", b"fake audio", "audio/webm")},
    )

    assert response.status_code == 200
    started_event = wait_for_event(client, session_id, "voice.tts_started")
    ready_event = wait_for_event(client, session_id, "voice.tts_ready")
    events = client.get("/events?limit=100").json()["events"]
    matching_types = [
        event["type"]
        for event in events
        if event["metadata"].get("session_id") == session_id
    ]
    assert "voice.upload_received" in matching_types
    assert "voice.transcribing_started" in matching_types
    assert "voice.transcribing_finished" in matching_types
    assert "voice.completed" in matching_types
    assert "voice.playback_ready" not in matching_types

    assert started_event["metadata"]["voice_request_id"] == response.json()["voice_request_id"]
    assert started_event["metadata"]["chunks_count"] >= 1
    assert ready_event["metadata"]["voice_request_id"] == response.json()["voice_request_id"]
    assert ready_event["metadata"]["audio_url"].startswith("/voice/audio/")
    assert ready_event["metadata"]["chunks_count"] >= 1
    assert ready_event["metadata"]["audio_duration_seconds"] > 0

    status_response = client.get(f"/voice/tts/{response.json()['voice_request_id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "ready"
    assert status_body["audio_url"].startswith("/voice/audio/")
    assert status_body["chunks_count"] >= 1
    assert status_body["audio_duration_seconds"] > 0


def test_voice_tts_status_returns_404_for_unknown_job(client: TestClient) -> None:
    response = client.get("/voice/tts/unknown")

    assert response.status_code == 404
    assert response.json()["detail"] == "Voice TTS job not found"


def test_voice_tts_status_returns_queued_before_background_tts_finishes(
    client: TestClient,
) -> None:
    original_tts_provider = app.state.voice_service._tts_provider
    app.state.voice_service._tts_provider = SlowTTSProvider()

    try:
        response = client.post(
            "/voice/chat",
            data={"session_id": "voice-tts-queued", "language": "ru"},
            files={"audio": ("voice.webm", b"fake audio", "audio/webm")},
        )
        assert response.status_code == 200
        voice_request_id = response.json()["voice_request_id"]

        status_response = client.get(f"/voice/tts/{voice_request_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "queued"

        ready_event = wait_for_event(client, "voice-tts-queued", "voice.tts_ready")
        assert ready_event["metadata"]["voice_request_id"] == voice_request_id
    finally:
        app.state.voice_service._tts_provider = original_tts_provider


def test_voice_chat_returns_502_on_llm_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(voice_route, "DeepSeekProvider", FailingLLMProvider)

    response = client.post(
        "/voice/chat",
        data={"session_id": "voice-llm-fail", "language": "ru"},
        files={"audio": ("voice.webm", b"fake audio", "audio/webm")},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "provider failed"


def test_voice_chat_returns_text_when_background_tts_fails(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    original_tts_provider = app.state.voice_service._tts_provider
    app.state.voice_service._tts_provider = FailingTTSProvider()
    session_id = "voice-tts-fail"

    try:
        with caplog.at_level(logging.INFO):
            response = client.post(
                "/voice/chat",
                data={"session_id": session_id, "language": "ru"},
                files={"audio": ("voice.webm", b"fake audio", "audio/webm")},
            )
            failed_event = wait_for_event(client, session_id, "voice.tts_failed")
    finally:
        app.state.voice_service._tts_provider = original_tts_provider

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Голос услышан"
    assert body["reply_audio_url"] is None
    assert body["tts_status"] == "queued"
    assert body["tts"]["duration_ms"] == 0

    assert failed_event["metadata"]["voice_request_id"] == body["voice_request_id"]
    assert "Voice synthesis fallback activated" in caplog.text
    assert "Traceback" not in caplog.text

    status_response = client.get(f"/voice/tts/{body['voice_request_id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "failed"
    assert status_body["audio_url"] is None
    assert status_body["error_type"] == "RuntimeError"
