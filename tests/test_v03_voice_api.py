import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.backend.main import app


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_voice_interrupt_uses_unified_session_cancellation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    async def interrupt(session_id: str, utterance_id: str | None) -> dict[str, int]:
        calls.append((session_id, utterance_id))
        return {"batch": 2}

    monkeypatch.setattr(app.state, "interrupt_voice_session", interrupt)

    response = client.post(
        "/voice/interrupt",
        json={"session_id": "barge-in", "utterance_id": "utterance-1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "cancelled",
        "session_id": "barge-in",
        "cancelled": {"batch": 2},
    }
    assert calls == [("barge-in", "utterance-1")]


def test_batch_voice_chat_endpoint_is_removed(client: TestClient) -> None:
    response = client.post(
        "/voice/chat",
        data={"session_id": "legacy", "language": "ru"},
        files={"audio": ("voice.webm", b"legacy", "audio/webm")},
    )
    assert response.status_code == 404


def test_voice_input_only_accepts_protocol_v3(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/voice-input/default?version=2"):
            pass


def test_voice_input_rejects_legacy_mode_field(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice-input/default?version=3") as socket:
        socket.send_json({
            "type": "voice.input.start",
            "protocol_version": 3,
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
            "language": "ru",
            "mode": "hands_free",
        })
        error = socket.receive_json()
        assert error["type"] == "voice.input.error"
        assert "mode" in error["message"]


def test_voice_input_disconnect_interrupts_downstream_generation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    async def interrupt(session_id: str, utterance_id: str | None) -> dict[str, int]:
        calls.append((session_id, utterance_id))
        return {"batch": 0}

    monkeypatch.setattr(app.state, "interrupt_voice_session", interrupt)

    with client.websocket_connect("/ws/voice-input/disconnect-lifecycle?version=3") as socket:
        socket.send_json({
            "type": "voice.input.start",
            "protocol_version": 3,
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
            "language": "ru",
        })
        assert socket.receive_json()["type"] == "voice.input.ready"

    assert calls == [("disconnect-lifecycle", None)]


def test_voice_input_graceful_stop_keeps_completed_turn_alive(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    async def interrupt(session_id: str, utterance_id: str | None) -> dict[str, int]:
        calls.append((session_id, utterance_id))
        return {"batch": 0}

    monkeypatch.setattr(app.state, "interrupt_voice_session", interrupt)

    with client.websocket_connect("/ws/voice-input/graceful-lifecycle?version=3") as socket:
        socket.send_json({
            "type": "voice.input.start",
            "protocol_version": 3,
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
            "language": "ru",
        })
        assert socket.receive_json()["type"] == "voice.input.ready"
        socket.send_json({"type": "voice.input.stop"})

    assert calls == []


def test_voice_input_reconnect_interrupts_previous_owner_generation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    async def interrupt(session_id: str, utterance_id: str | None) -> dict[str, int]:
        calls.append((session_id, utterance_id))
        return {"batch": 0}

    monkeypatch.setattr(app.state, "interrupt_voice_session", interrupt)
    start = {
        "type": "voice.input.start",
        "protocol_version": 3,
        "sample_rate": 16000,
        "channels": 1,
        "format": "pcm_s16le",
        "language": "ru",
    }

    with client.websocket_connect("/ws/voice-input/reconnect-lifecycle?version=3") as first:
        first.send_json(start)
        assert first.receive_json()["type"] == "voice.input.ready"
        with client.websocket_connect("/ws/voice-input/reconnect-lifecycle?version=3") as second:
            second.send_json(start)
            assert second.receive_json()["type"] == "voice.input.ready"
            second.send_json({"type": "voice.input.stop"})

    assert calls == [("reconnect-lifecycle", None)]
