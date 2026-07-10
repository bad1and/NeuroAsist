import logging

import anyio
import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import LLMResponse


@pytest.fixture
def agent() -> CharacterAgent:
    return CharacterAgent(llm_provider=None, history=None, history_limit=0)


def test_parse_response_accepts_valid_json(agent: CharacterAgent) -> None:
    result = agent._parse_response(
        '{"reply":"Привет","emotion":"happy","intent":"casual_chat"}'
    )

    assert result == {
        "reply": "Привет",
        "emotion": "happy",
        "intent": "casual_chat",
    }


def test_parse_response_accepts_json_markdown_fence(agent: CharacterAgent) -> None:
    result = agent._parse_response(
        '```json\n{"reply":"Привет","emotion":"happy","intent":"casual_chat"}\n```'
    )

    assert result == {
        "reply": "Привет",
        "emotion": "happy",
        "intent": "casual_chat",
    }


def test_parse_response_accepts_json_with_extra_text(agent: CharacterAgent) -> None:
    result = agent._parse_response(
        'Ответ:\n{"reply":"Привет","emotion":"happy","intent":"casual_chat"}'
    )

    assert result == {
        "reply": "Привет",
        "emotion": "happy",
        "intent": "casual_chat",
    }


@pytest.mark.parametrize(
    "raw_content",
    [
        "Привет, я не JSON",
        '["hello"]',
        '{"reply":"","emotion":"happy","intent":"casual_chat"}',
        '{"reply":"Привет","emotion":"banana","intent":"casual_chat"}',
        '{"reply":"Привет","emotion":"happy","intent":"dance"}',
    ],
)
def test_parse_response_uses_fallback_for_invalid_llm_response(
    agent: CharacterAgent,
    raw_content: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result = agent._parse_response(raw_content)

    assert result == {
        "reply": raw_content.strip() or "Модель вернула пустой ответ. Попробуй повторить.",
        "emotion": "neutral",
        "intent": "unknown",
    }
    assert "Invalid LLM JSON response, using fallback" in caplog.text
    assert "raw_length=" in caplog.text
    assert raw_content not in caplog.text


class SequencedLLMProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    async def generate(self, messages):
        content = self.responses[self.calls]
        self.calls += 1
        return LLMResponse(content=content, model="test-model")


class InMemoryHistory:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []

    def get_recent_messages(self, session_id: str, limit: int):
        return []

    def save_message(self, session_id: str, role: str, content: str) -> None:
        self.saved.append((session_id, role, content))


def test_handle_user_message_retries_invalid_json_once() -> None:
    provider = SequencedLLMProvider(
        [
            "Привет, я не JSON",
            '{"reply":"Исправлено","emotion":"happy","intent":"casual_chat"}',
        ]
    )
    history = InMemoryHistory()
    agent = CharacterAgent(provider, history, history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "Привет")

    assert provider.calls == 2
    assert result == {
        "reply": "Исправлено",
        "emotion": "happy",
        "intent": "casual_chat",
    }
    assert history.saved == [
        ("s1", "user", "Привет"),
        ("s1", "assistant", "Исправлено"),
    ]


def test_handle_user_message_uses_deterministic_fallback_for_empty_model_response() -> None:
    provider = SequencedLLMProvider(["   ", "\n\t"])
    history = InMemoryHistory()
    agent = CharacterAgent(provider, history, history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "Да нормально")

    assert provider.calls == 2
    assert result == {
        "reply": 'Я услышал: "Да нормально". Но модель вернула пустой ответ. Попробуй повторить.',
        "emotion": "neutral",
        "intent": "unknown",
    }
    assert "Не смог корректно разобрать ответ модели" not in result["reply"]
    assert history.saved == [("s1", "user", "Да нормально")]


def test_handle_user_message_keeps_first_raw_text_if_retry_is_empty() -> None:
    provider = SequencedLLMProvider(["Нормальный текст без JSON", "   "])
    history = InMemoryHistory()
    agent = CharacterAgent(provider, history, history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "Привет")

    assert provider.calls == 2
    assert result == {
        "reply": "Нормальный текст без JSON",
        "emotion": "neutral",
        "intent": "unknown",
    }
    assert history.saved == [("s1", "user", "Привет")]
