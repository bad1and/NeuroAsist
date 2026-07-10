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
    assert body["model"]
    assert body["available_personalities"] == ["default"]
    assert body["voice_language"] == "ru"
    assert body["voice_stt_model"] == "small"
    assert body["voice_tts_enabled"] is True
    assert body["voice_tts_voice"]
    assert body["available_voice_languages"] == ["auto", "ru", "en"]
    assert body["available_tts_voices"]
    assert "api_key" not in body
    assert "DEEPSEEK_API_KEY" not in response.text


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
        if event["metadata"].get("session_id") == session_id
    ]
    assert [event["type"] for event in matching[-2:]] == [
        "chat.started",
        "chat.completed",
    ]
    assert matching[-2]["metadata"]["message_length"] == 5
    assert matching[-1]["metadata"]["reply_length"] == 6


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
