from fastapi.testclient import TestClient
import pytest

from apps.backend.app.api.routes import chat as chat_route
from apps.backend.app.llm.base import LLMProviderError, LLMResponse
from apps.backend.main import app


class SuccessfulLLMProvider:
    def __init__(self, settings, model=None):
        self.settings = settings
        self.model = model

    async def generate(self, messages):
        return LLMResponse(
            content='{"reply":"Привет","emotion":"happy","intent":"casual_chat"}',
            model=self.model or "test-model",
        )


class FailingLLMProvider:
    def __init__(self, settings, model=None):
        self.settings = settings
        self.model = model

    async def generate(self, messages):
        raise LLMProviderError("provider failed")


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_status_returns_safe_public_status(client: TestClient) -> None:
    response = client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "ok"
    assert body["llm_provider"] == "deepseek"
    assert body["llm_model"]
    assert isinstance(body["api_key_configured"], bool)
    assert "api_key" not in body


def test_public_settings_does_not_return_api_key(client: TestClient) -> None:
    response = client.get("/settings/public")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "deepseek"
    assert body["model"] == app.state.settings.deepseek_model
    assert "available_models" not in body
    assert body["available_personalities"] == ["default"]
    assert body["voice_language"] == "ru"
    assert body["voice_stt_model"] == "v3_rnnt"
    assert body["voice_tts_enabled"] is True
    assert body["voice_tts_provider"] == app.state.voice_service.tts_provider.name
    assert body["voice_tts_style"] == "auto"
    assert body["voice_tts_voice"]
    assert body["voice_playback_rate"] == 1.0
    assert 1 <= body["voice_live_playback_prebuffer_segments"] <= 4
    assert 0 <= body["voice_live_playback_prebuffer_ms"] <= 1500
    assert body["available_voice_languages"] == ["auto", "ru", "en"]
    assert body["available_tts_voices"]
    assert "api_key" not in body
    assert "DEEPSEEK_API_KEY" not in response.text


def test_runtime_settings_rejects_model_patch(client: TestClient) -> None:
    response = client.patch(
        "/settings/runtime",
        json={"model": "deepseek-v4-pro"},
    )

    assert response.status_code == 422


def test_runtime_voice_settings_can_be_updated(client: TestClient) -> None:
    original = client.get("/settings/public").json()
    target_voice = "baya" if "baya" in original["available_tts_voices"] else original["voice_tts_voice"]

    try:
        response = client.patch(
            "/settings/runtime",
            json={
                "voice_language": "ru",
                "voice_tts_voice": target_voice,
                "voice_playback_rate": 1.15,
                "voice_live_playback_prebuffer_segments": 3,
                "voice_live_playback_prebuffer_ms": 500,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["voice_tts_voice"] == target_voice
        assert body["voice_playback_rate"] == 1.15
        assert body["voice_live_playback_prebuffer_segments"] == 3
        assert body["voice_live_playback_prebuffer_ms"] == 500
    finally:
        client.patch(
            "/settings/runtime",
            json={
                "voice_language": original["voice_language"],
                "voice_tts_voice": original["voice_tts_voice"],
                "voice_playback_rate": original["voice_playback_rate"],
                "voice_live_playback_prebuffer_segments": original["voice_live_playback_prebuffer_segments"],
                "voice_live_playback_prebuffer_ms": original["voice_live_playback_prebuffer_ms"],
            },
        )


def test_voice_style_can_be_changed_until_restart(client: TestClient) -> None:
    response = client.patch("/settings/voice-style", json={"voice_tts_style": "energetic"})

    assert response.status_code == 200
    assert response.json()["voice_tts_style"] == "energetic"

    unsupported = client.patch("/settings/voice-style", json={"voice_tts_style": "very-loud"})

    assert unsupported.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"voice_tts_voice": "unknown"},
        {"voice_playback_rate": 0.5},
        {"voice_playback_rate": 1.5},
        {"voice_live_playback_prebuffer_segments": 0},
        {"voice_live_playback_prebuffer_segments": 5},
        {"voice_live_playback_prebuffer_ms": -1},
        {"voice_live_playback_prebuffer_ms": 2000},
    ],
)
def test_runtime_voice_settings_validate_ranges(client: TestClient, payload: dict) -> None:
    response = client.patch("/settings/runtime", json=payload)

    assert response.status_code == 400


def test_events_returns_event_list(client: TestClient) -> None:
    response = client.get("/events?limit=10")

    assert response.status_code == 200
    assert isinstance(response.json()["events"], list)


def test_chat_publishes_started_and_completed_events(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_route, "DeepSeekProvider", SuccessfulLLMProvider)
    session_id = "events-success-test"

    response = client.post(
        "/chat",
        json={"session_id": session_id, "message": "hello"},
    )

    assert response.status_code == 200
    events = client.get("/events?limit=50").json()["events"]
    matching = [
        event
        for event in events
        if event["metadata"].get("session_id") == session_id and event["type"].startswith("chat.")
    ]
    assert [event["type"] for event in matching[-2:]] == [
        "chat.started",
        "chat.completed",
    ]
    assert matching[-2]["metadata"]["message_length"] == 5
    assert matching[-1]["metadata"]["reply_length"] == 6


def test_chat_returns_memory_update_for_balanced_identity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_route, "DeepSeekProvider", SuccessfulLLMProvider)

    response = client.post("/chat", json={"session_id": "memory-update", "message": "Меня зовут Роман"})

    assert response.status_code == 200
    update = response.json()["memory_updates"][0]
    assert update["status"] == "active"
    assert update["action"] == "saved"
    assert update["predicate"] == "name"
    assert update["id"]


def test_chat_publishes_llm_error_event_and_returns_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_route, "DeepSeekProvider", FailingLLMProvider)
    session_id = "events-error-test"

    response = client.post(
        "/chat",
        json={"session_id": session_id, "message": "hello"},
    )

    assert response.status_code == 502
    events = client.get("/events?limit=50").json()["events"]
    matching = [
        event
        for event in events
        if event["metadata"].get("session_id") == session_id
    ]
    assert any(event["type"] == "llm.error" for event in matching)
    assert any(event["type"] == "chat.failed" for event in matching)


def test_websocket_events_receives_backend_event(client: TestClient) -> None:
    with client.websocket_connect("/ws/events") as websocket:
        event = websocket.receive_json()

    assert event["type"] == "backend.status"
    assert event["message"] == "WebSocket client connected"


def test_cors_allows_localhost_dev_ports(client: TestClient) -> None:
    response = client.options(
        "/status",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"
