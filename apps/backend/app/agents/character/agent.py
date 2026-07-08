import json
import logging
from typing import Any

from apps.backend.app.agents.character.prompts import CHARACTER_SYSTEM_PROMPT
from apps.backend.app.llm.base import ChatMessage, LLMProvider
from apps.backend.app.schemas.character import CharacterLLMResponse
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory

logger = logging.getLogger(__name__)


class CharacterAgent:
    def __init__(
        self,
        llm_provider: LLMProvider,
        history: SQLiteMessageHistory,
        history_limit: int,
    ) -> None:
        self._llm_provider = llm_provider
        self._history = history
        self._history_limit = history_limit

    async def handle_user_message(self, session_id: str, user_text: str) -> dict[str, str]:
        context = self._history.get_recent_messages(session_id, limit=self._history_limit)
        messages = [
            ChatMessage(role="system", content=CHARACTER_SYSTEM_PROMPT),
            *context,
            ChatMessage(role="user", content=user_text),
        ]

        llm_response = await self._llm_provider.generate(messages)
        parsed = self._parse_response(llm_response.content)

        self._history.save_message(session_id, "user", user_text)
        self._history.save_message(session_id, "assistant", parsed["reply"])

        return parsed

    def _parse_response(self, raw_content: str) -> dict[str, str]:
        try:
            payload: Any = json.loads(raw_content)
        except json.JSONDecodeError:
            return self._fallback_response(raw_content, "json_decode_error")

        if not isinstance(payload, dict):
            return self._fallback_response(raw_content, "non_object_payload")

        try:
            parsed = CharacterLLMResponse.model_validate(payload)
        except ValueError:
            return self._fallback_response(raw_content, "schema_validation_error")

        return parsed.model_dump()

    def _fallback_response(self, raw_content: str, reason: str) -> dict[str, str]:
        logger.warning(
            "Invalid LLM JSON response, using fallback: reason=%s raw_length=%s",
            reason,
            len(raw_content),
        )
        return {
            "reply": raw_content.strip() or "Не смог корректно разобрать ответ модели.",
            "emotion": "neutral",
            "intent": "unknown",
        }
