import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from apps.backend.app.agents.character.prompts import (
    CHARACTER_REPAIR_PROMPT,
    CHARACTER_SYSTEM_PROMPT,
)
from apps.backend.app.llm.base import ChatMessage, LLMProvider
from apps.backend.app.schemas.character import CharacterLLMResponse
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParseResult:
    payload: dict[str, str]
    valid: bool
    reason: str | None = None


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
        empty_reply = self._empty_model_fallback(user_text)

        llm_response = await self._llm_provider.generate(messages)
        parsed = self._parse_response_result(
            llm_response.content,
            session_id=session_id,
            empty_fallback_reply=empty_reply,
        )
        if not parsed.valid:
            first_invalid = parsed
            repair_messages = [
                ChatMessage(role="system", content=CHARACTER_REPAIR_PROMPT),
                ChatMessage(
                    role="user",
                    content=(
                        "Запрос пользователя:\n"
                        f"{user_text}\n\n"
                        "Невалидный ответ модели:\n"
                        f"{llm_response.content!r}\n\n"
                        "Верни один валидный JSON по схеме."
                    ),
                ),
            ]
            repair_response = await self._llm_provider.generate(repair_messages)
            parsed = self._parse_response_result(
                repair_response.content,
                session_id=session_id,
                empty_fallback_reply=empty_reply,
                event_type="llm.invalid_json_retry_failed",
            )
            if (
                not parsed.valid
                and not repair_response.content.strip()
                and first_invalid.payload["reply"].strip()
            ):
                parsed = first_invalid

        self._history.save_message(session_id, "user", user_text)
        if parsed.valid:
            self._history.save_message(session_id, "assistant", parsed.payload["reply"])

        return parsed.payload

    def _parse_response(
        self,
        raw_content: str,
        session_id: str | None = None,
    ) -> dict[str, str]:
        return self._parse_response_result(raw_content, session_id=session_id).payload

    def _parse_response_result(
        self,
        raw_content: str,
        session_id: str | None = None,
        empty_fallback_reply: str = "Модель вернула пустой ответ. Попробуй повторить.",
        event_type: str = "llm.invalid_json",
    ) -> _ParseResult:
        json_content = self._extract_json(raw_content)

        try:
            payload: Any = json.loads(json_content)
        except json.JSONDecodeError:
            return self._fallback_response(
                raw_content,
                "json_decode_error",
                session_id,
                empty_fallback_reply,
                event_type,
            )

        if not isinstance(payload, dict):
            return self._fallback_response(
                raw_content,
                "non_object_payload",
                session_id,
                empty_fallback_reply,
                event_type,
            )

        try:
            parsed = CharacterLLMResponse.model_validate(payload)
        except ValueError:
            return self._fallback_response(
                raw_content,
                "schema_validation_error",
                session_id,
                empty_fallback_reply,
                event_type,
            )

        return _ParseResult(parsed.model_dump(), valid=True)

    def _extract_json(self, raw_content: str) -> str:
        stripped = raw_content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
        if fenced:
            return fenced.group(1).strip()

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            return stripped[start : end + 1]

        return stripped

    def _fallback_response(
        self,
        raw_content: str,
        reason: str,
        session_id: str | None,
        empty_fallback_reply: str,
        event_type: str,
    ) -> _ParseResult:
        logger.warning(
            "Invalid LLM JSON response, using fallback: reason=%s raw_length=%s",
            reason,
            len(raw_content),
        )
        if self._event_publisher is not None:
            metadata: dict[str, Any] = {
                "reason": reason,
                "raw_length": len(raw_content),
                "raw_preview": raw_content.strip()[:120],
            }
            if session_id is not None:
                metadata["session_id"] = session_id

            self._event_publisher(
                event_type,
                "warning",
                "Invalid LLM JSON response, using fallback",
                metadata,
            )

        stripped = raw_content.strip()
        return _ParseResult(
            {
                "reply": stripped or empty_fallback_reply,
                "emotion": "neutral",
                "intent": "unknown",
            },
            valid=False,
            reason=reason,
        )

    def _empty_model_fallback(self, user_text: str) -> str:
        return f'Я услышал: "{user_text}". Но модель вернула пустой ответ. Попробуй повторить.'
