import json
import logging
import re
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any, Callable

from apps.backend.app.agents.character.prompts import (
    CHARACTER_JSON_PROMPT,
    CHARACTER_LIVE_PROMPT,
    CHARACTER_REPAIR_PROMPT,
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
            ChatMessage(role="system", content=CHARACTER_JSON_PROMPT),
            *context,
            ChatMessage(role="user", content=user_text),
        ]
        empty_reply = self._empty_model_fallback(user_text)

        llm_response = await self._llm_provider.generate(messages)
        parsed = self._parse_response_result(
            llm_response.content,
            session_id=session_id,
            empty_fallback_reply=empty_reply,
            report_invalid=False,
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
                report_invalid=True,
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

    async def stream_user_message(
        self, session_id: str, user_text: str,
        stored_reply_transform: Callable[[str], str] | None = None,
    ) -> AsyncIterator[str]:
        """Stream plain reply text and commit history only after clean completion."""
        context = self._history.get_recent_messages(session_id, limit=self._history_limit)
        messages = [
            ChatMessage(role="system", content=CHARACTER_LIVE_PROMPT),
            *context,
            ChatMessage(role="user", content=user_text),
        ]
        chunks: list[str] = []
        async for delta in self._llm_provider.stream(messages):
            if not delta:
                continue
            chunks.append(delta)
            yield delta
        reply = "".join(chunks).strip()
        if stored_reply_transform is not None:
            reply = stored_reply_transform(reply)
        if not reply:
            reply = self._empty_model_fallback(user_text)
            yield reply
        self._history.save_message(session_id, "user", user_text)
        self._history.save_message(session_id, "assistant", reply)

    @staticmethod
    def classify_intent(user_text: str) -> str:
        text = user_text.strip().lower()
        if not text:
            return "unknown"
        task_markers = (
            "сделай", "создай", "запусти", "открой", "покажи", "напиши",
            "помоги", "please", "create", "make", "run", "open", "write",
        )
        if any(marker in text for marker in task_markers):
            return "task_request"
        if "?" in text or text.startswith(("кто ", "что ", "где ", "когда ", "как ", "почему ", "why ", "how ", "what ", "who ")):
            return "question"
        return "casual_chat"

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
        report_invalid: bool = True,
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
                report_invalid,
            )

        if not isinstance(payload, dict):
            return self._fallback_response(
                raw_content,
                "non_object_payload",
                session_id,
                empty_fallback_reply,
                event_type,
                report_invalid,
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
                report_invalid,
            )

        payload = parsed.model_dump(exclude_defaults=True)
        nested_reply = self._extract_nested_reply(payload["reply"])
        if nested_reply is not None:
            payload["reply"] = nested_reply

        # Do not change the v0.4 public agent result when the optional gesture was absent.
        return _ParseResult(payload, valid=True)

    @staticmethod
    def _extract_nested_reply(reply: str) -> str | None:
        """Unwrap a JSON response accidentally serialized into the reply field."""
        candidate = reply.strip()
        if not candidate.startswith("{"):
            return None
        try:
            nested = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(nested, dict):
            return None
        value = nested.get("reply")
        return value.strip() if isinstance(value, str) and value.strip() else None

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
        report_invalid: bool,
    ) -> _ParseResult:
        if report_invalid:
            logger.warning(
                "Invalid LLM JSON response, using fallback after repair attempt: reason=%s raw_length=%s",
                reason,
                len(raw_content),
            )
        if report_invalid and self._event_publisher is not None:
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
        # A partial/invalid JSON object is transport metadata, not a user-facing reply.
        # Showing it verbatim was the source of occasional JSON messages in the UI.
        if self._looks_like_structured_content(stripped):
            stripped = ""
        return _ParseResult(
            {
                "reply": stripped or empty_fallback_reply,
                "emotion": "neutral",
                "intent": "unknown",
            },
            valid=False,
            reason=reason,
        )

    @staticmethod
    def _looks_like_structured_content(value: str) -> bool:
        return value.startswith(("{", "[", "```"))

    def _empty_model_fallback(self, user_text: str) -> str:
        return f'Я услышал: "{user_text}". Но модель вернула пустой ответ. Попробуй повторить.'
