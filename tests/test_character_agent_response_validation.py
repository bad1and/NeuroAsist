import logging

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent


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
        "reply": raw_content.strip() or "Не смог корректно разобрать ответ модели.",
        "emotion": "neutral",
        "intent": "unknown",
    }
    assert "Invalid LLM JSON response, using fallback" in caplog.text
    assert "raw_length=" in caplog.text
    assert raw_content not in caplog.text
