from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from apps.backend.app.avatar.connection_manager import AvatarConnectionManager
from apps.backend.app.avatar.protocol import AvatarProtocolError, parse_incoming
from apps.backend.app.avatar.service import AvatarService
from apps.backend.app.events.bus import EventBus
from apps.backend.app.voice.orchestrator import SpeechOrchestrator
from apps.backend.app.voice.providers import MockTTSProvider
from apps.backend.app.voice.service import VoiceService
from apps.backend.main import app


class FakeSocket:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, message: dict) -> None:
        if self.fail:
            raise RuntimeError("dead socket")
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_avatar_manager_broadcast_isolates_dead_client() -> None:
    manager = AvatarConnectionManager()
    alive = await manager.register(FakeSocket())
    dead = await manager.register(FakeSocket(fail=True))

    result = await manager.broadcast({"type": "avatar.ping"})

    assert result.attempted == 2
    assert result.sent == 1
    assert result.failed == 1
    assert len(alive.websocket.sent) == 1
    assert await manager.get(dead.client_id) is None


@pytest.mark.anyio
async def test_avatar_manager_removes_stale_clients() -> None:
    manager = AvatarConnectionManager()
    client = await manager.register(FakeSocket())
    client.last_heartbeat_at -= timedelta(seconds=20)

    stale = await manager.stale_clients(10)

    assert [item.client_id for item in stale] == [client.client_id]
    assert await manager.status_clients() == []


def test_avatar_protocol_validates_type_and_version() -> None:
    envelope, payload = parse_incoming({
        "protocol_version": 1,
        "type": "avatar.hello",
        "message_id": "m",
        "timestamp": "2026-01-01T00:00:00Z",
        "session_id": "default",
        "payload": {"client_name": "Unity", "client_version": "0.4", "supported_protocol_versions": [1]},
    })
    assert envelope.type == "avatar.hello"
    assert payload.client_name == "Unity"
    with pytest.raises(AvatarProtocolError, match="Unsupported"):
        parse_incoming({"protocol_version": 2, "type": "avatar.pong", "payload": {}})
    with pytest.raises(AvatarProtocolError, match="Unknown"):
        parse_incoming({"protocol_version": 1, "type": "avatar.unknown", "payload": {}})


@pytest.mark.anyio
async def test_disabled_avatar_service_is_safe_noop() -> None:
    service = AvatarService(AvatarConnectionManager(), EventBus(), enabled=False, heartbeat_interval_seconds=1, client_timeout_seconds=2)
    result = await service.stop(session_id="default")
    status = await service.status()
    assert result.skipped is True
    assert status.enabled is False
    assert status.client_count == 0


@pytest.mark.anyio
async def test_hello_and_playback_events_update_client_status() -> None:
    events = EventBus()
    manager = AvatarConnectionManager()
    client = await manager.register(FakeSocket())
    service = AvatarService(manager, events, enabled=True, heartbeat_interval_seconds=1, client_timeout_seconds=2)
    hello, hello_payload = parse_incoming({
        "protocol_version": 1, "type": "avatar.hello", "message_id": "hello", "timestamp": "2026-01-01T00:00:00Z", "session_id": "s",
        "payload": {"client_name": "Unity", "client_version": "0.4", "supported_protocol_versions": [1], "platform": "WindowsPlayer"},
    })
    started, started_payload = parse_incoming({
        "protocol_version": 1, "type": "avatar.playback.started", "message_id": "started", "timestamp": "2026-01-01T00:00:01Z", "session_id": "s",
        "payload": {"utterance_id": "utterance"},
    })
    await service.inbound(client.client_id, hello, hello_payload)
    await service.inbound(client.client_id, started, started_payload)
    status = await service.status()
    assert status.clients[0].client_name == "Unity"
    assert status.clients[0].current_utterance_id == "utterance"
    assert [event.type for event in events.get_recent_events()] == ["avatar.hello", "avatar.speaking_started"]


@pytest.mark.anyio
async def test_orchestrator_sends_only_after_ready_wav(tmp_path, monkeypatch) -> None:
    class Settings:
        voice_stt_provider = "mock"
        voice_tts_provider = "mock"
        voice_tts_max_chars = 1200
        voice_tts_background_timeout_seconds = 2
        voice_audio_dir = str(tmp_path / "audio")

        @property
        def voice_audio_path(self):
            return tmp_path / "audio"

    settings = Settings()
    voice = VoiceService(settings)
    voice._tts_provider = MockTTSProvider()
    manager = AvatarConnectionManager()
    socket = FakeSocket()
    await manager.register(socket)
    service = AvatarService(manager, EventBus(), enabled=True, heartbeat_interval_seconds=1, client_timeout_seconds=2)
    orchestrator = SpeechOrchestrator(voice, EventBus(), settings, service)

    job_id = orchestrator.enqueue(session_id="s", reply="Привет", emotion="happy", intent="test", voice="xenia")
    while voice.get_tts_job(job_id)["status"] == "queued":
        await __import__("asyncio").sleep(0.01)

    job = voice.get_tts_job(job_id)
    assert job["status"] == "ready"
    assert job["audio_url"].startswith("/voice/audio/")
    assert socket.sent[0]["type"] == "avatar.speak"
    assert socket.sent[0]["payload"]["audio_url"] == job["audio_url"]
    await orchestrator.close()


def test_avatar_http_status_and_test_commands(monkeypatch) -> None:
    service = app.state.avatar_service
    previous = service.enabled
    service.enabled = False
    monkeypatch.setattr(app.state.speech_orchestrator, "enqueue", lambda **_: "test-job")
    try:
        with TestClient(app) as client:
            status = client.get("/avatar/status")
            assert status.status_code == 200
            assert status.json()["enabled"] is False
            assert client.post("/avatar/test/emotion", json={"emotion": "happy"}).json()["skipped"] is True
            assert client.post("/avatar/stop", json={}).json()["skipped"] is True
            assert client.post("/avatar/test/speak", json={"text": "test"}).json()["voice_request_id"] == "test-job"
    finally:
        service.enabled = previous
