import logging

from fastapi.testclient import TestClient
import pytest

from apps.backend.app.api.routes import chat as chat_route
from apps.backend.app.llm.base import LLMProviderError
from apps.backend.main import app


class FailingLLMProvider:
    def __init__(self, settings):
        self.settings = settings

    async def generate(self, messages):
        raise LLMProviderError("provider failed")


class UnexpectedFailingProvider:
    def __init__(self, settings):
        self.settings = settings

    async def generate(self, messages):
        raise RuntimeError("surprise failure")


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
