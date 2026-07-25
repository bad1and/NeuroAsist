import logging

from fastapi.testclient import TestClient
import pytest

from apps.backend.app.api.routes import chat as chat_route
from apps.backend.app.llm.base import LLMProviderError
from apps.backend.main import app


class FailingLLMProvider:
    def __init__(self, settings, model=None):
        self.settings = settings
        self.model = model

    async def generate(self, messages):
        raise LLMProviderError("provider failed")


class UnexpectedFailingProvider:
    def __init__(self, settings, model=None):
        self.settings = settings
        self.model = model

    async def generate(self, messages):
        raise RuntimeError("surprise failure")


class SuccessfulLLMProvider:
    def __init__(self, settings, model=None):
        self.model = model

    async def generate(self, messages):
        from apps.backend.app.llm.base import LLMResponse
        return LLMResponse(content='{"reply":"Готово","emotion":"neutral","intent":"casual_chat"}', model="test")


class TTSRecorder:
    def bind_runtime(self, voice_service, settings) -> None:
        self.voice_service = voice_service
        self.settings = settings

    def enqueue(self, **kwargs) -> str:
        self.kwargs = kwargs
        return "text-tts-job"


class LiveManagerRecorder:
    def __init__(self) -> None:
        self.kwargs = None

    def connected(self, _session_id: str) -> bool:
        return True

    async def start(self, **kwargs) -> None:
        self.kwargs = kwargs


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_chat_logs_llm_provider_error_and_returns_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_user_text = "do not log this full user text"
    monkeypatch.setattr(chat_route, "DeepSeekProvider", FailingLLMProvider)

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/chat",
            json={"session_id": "logging-test", "message": secret_user_text},
        )

    assert response.status_code == 502
    assert "LLM provider failed during chat request" in caplog.text
    assert "message_length=30" in caplog.text
    assert secret_user_text not in caplog.text


def test_chat_logs_unexpected_error_and_returns_safe_500(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_user_text = "another full message that should stay out of logs"
    monkeypatch.setattr(chat_route, "DeepSeekProvider", UnexpectedFailingProvider)

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/chat",
            json={"session_id": "logging-test", "message": secret_user_text},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal chat error"}
    assert "Unexpected /chat failure" in caplog.text
    assert "message_length=49" in caplog.text
    assert secret_user_text not in caplog.text


def test_text_chat_queues_tts_when_avatar_is_disabled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = TTSRecorder()
    monkeypatch.setattr(chat_route, "DeepSeekProvider", SuccessfulLLMProvider)
    monkeypatch.setattr(app.state, "speech_orchestrator", recorder)
    monkeypatch.setattr(app.state, "settings", app.state.settings.model_copy(update={"voice_tts_enabled": True, "avatar_enabled": False}))

    response = client.post("/chat", json={"session_id": "text-tts", "message": "Привет"})

    assert response.status_code == 200
    assert response.json()["tts_status"] == "queued"
    assert response.json()["voice_request_id"] == "text-tts-job"
    assert recorder.kwargs["reply"] == "Готово"


def test_live_text_chat_uses_live_voice_channel_without_stt(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = LiveManagerRecorder()
    monkeypatch.setattr(app.state, "voice_session_manager", manager)
    monkeypatch.setattr(app.state, "settings", app.state.settings.model_copy(update={"voice_tts_enabled": True}))

    response = client.post("/chat/live", json={"session_id": "typed-live", "message": "Привет текстом"})

    assert response.status_code == 200
    assert response.json()["transcript"] == "Привет текстом"
    assert manager.kwargs is not None
    assert manager.kwargs["transcript"] == "Привет текстом"
    assert manager.kwargs["input_mode"] == "text"
