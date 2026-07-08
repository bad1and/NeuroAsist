import json
import logging
from typing import Any, Callable

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
        event_publisher: Callable[[str, str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._history = history
        self._history_limit = history_limit
        self._event_publisher = event_publisher

    async def handle_user_message(self, session_id: str, user_text: str) -> dict[str, str]:
        context = self._history.get_recent_messages(session_id, limit=self._history_limit)
        messages = [
            ChatMessage(role="system", content=CHARACTER_SYSTEM_PROMPT),
            *context,
            ChatMessage(role="user", content=user_text),
        ]

        llm_response = await self._llm_provider.generate(messages)
        parsed = self._parse_response(llm_response.content, session_id=session_id)

        self._history.save_message(session_id, "user", user_text)
        self._history.save_message(session_id, "assistant", parsed["reply"])

        return parsed

    def _parse_response(
        self,
        raw_content: str,
        session_id: str | None = None,
    ) -> dict[str, str]:
        try:
            payload: Any = json.loads(raw_content)
        except json.JSONDecodeError:
            return self._fallback_response(raw_content, "json_decode_error", session_id)

        if not isinstance(payload, dict):
            return self._fallback_response(raw_content, "non_object_payload", session_id)

        try:
            parsed = CharacterLLMResponse.model_validate(payload)
        except ValueError:
            return self._fallback_response(raw_content, "schema_validation_error", session_id)

        return parsed.model_dump()

    def _fallback_response(
        self,
        raw_content: str,
        reason: str,
        session_id: str | None,
    ) -> dict[str, str]:
        logger.warning(
            "Invalid LLM JSON response, using fallback: reason=%s raw_length=%s",
            reason,
            len(raw_content),
        )
        if self._event_publisher is not None:
            metadata: dict[str, Any] = {
                "reason": reason,
                "raw_length": len(raw_content),
            }
            if session_id is not None:
                metadata["session_id"] = session_id

            self._event_publisher(
                "llm.invalid_json",
                "warning",
                "Invalid LLM JSON response, using fallback",
                metadata,
            )

        return {
            "reply": raw_content.strip() or "Не смог корректно разобрать ответ модели.",
            "emotion": "neutral",
            "intent": "unknown",
        }
