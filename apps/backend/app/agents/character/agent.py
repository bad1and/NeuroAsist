import json
import logging
import re
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any, Callable

from apps.backend.app.agents.character.prompts import (
    CHARACTER_REPAIR_PROMPT,
    character_json_prompt,
    character_live_prompt,
)
from apps.backend.app.agents.character.persona import get_persona
from apps.backend.app.agents.character.protocol import classify_intent, legacy_result, parse_turn
from apps.backend.app.llm.base import ChatMessage, LLMProvider
from apps.backend.app.schemas.character import CharacterTurn
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParseResult:
    payload: dict[str, Any]
    valid: bool
    reason: str | None = None
    turn: CharacterTurn | None = None


class CharacterAgent:
    def __init__(
        self,
        llm_provider: LLMProvider,
        history: SQLiteMessageHistory,
        history_limit: int,
        event_publisher: Callable[[str, str, str, dict[str, Any]], None] | None = None,
        context_manager=None,
        memory_service=None,
        persona_name: str = "default",
    ) -> None:
        self._llm_provider = llm_provider
        self._history = history
        self._history_limit = history_limit
        self._event_publisher = event_publisher
        self._context_manager = context_manager
        self._memory_service = memory_service
        self._persona = get_persona(persona_name)
        self.last_turn: CharacterTurn | None = None
        self.last_memory_updates: list[dict[str, str]] = []
        self._last_user_message = None

    async def handle_user_message(self, session_id: str, user_text: str, input_mode: str = "text") -> dict[str, Any]:
        context = self._context_manager.build(user_text).messages if self._context_manager else self._history.get_recent_messages(session_id, limit=self._history_limit)
        self.last_memory_updates = self._persist_user_message(session_id, user_text, input_mode)
        messages = [
            ChatMessage(role="system", content=character_json_prompt(self._persona)),
            *context,
            ChatMessage(role="user", content=user_text),
        ]
        empty_reply = self._empty_model_fallback(user_text)

        llm_response = await self._llm_provider.generate(messages)
        parsed = self._parse_response_result(
            llm_response.content,
            session_id=session_id,
            user_text=user_text,
            empty_fallback_reply=empty_reply,
            report_invalid=False,
        )
        if not parsed.valid:
            first_invalid = parsed
            logger.info(
                "Invalid LLM JSON response; retrying with full context: reason=%s raw_length=%s",
                parsed.reason,
                len(llm_response.content),
            )
            if self._event_publisher is not None:
                self._event_publisher(
                    "llm.invalid_json_retry",
                    "warning",
                    "Invalid LLM JSON response; retrying",
                    {"session_id": session_id, "reason": parsed.reason, "raw_length": len(llm_response.content)},
                )
            # The original full prompt has persona and conversation context.  A
            # standalone repair prompt often caused another empty answer.
            repair_messages = [*messages, ChatMessage(role="system", content=CHARACTER_REPAIR_PROMPT)]
            repair_response = await self._llm_provider.generate(repair_messages)
            parsed = self._parse_response_result(
                repair_response.content,
                session_id=session_id,
                user_text=user_text,
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

        # The modern path deliberately has one writer: the background extractor.
        # Keeping Character Protocol candidates on that path as well prevents a
        # normal text turn from being saved twice by two independent DeepSeek calls.
        if (
            parsed.valid
            and parsed.turn is not None
            and self._memory_service is not None
            and self._memory_service.llm_extraction_enabled
            and not self._memory_service.uses_background_extraction
        ):
            created = self._memory_service.apply_llm_candidates(parsed.turn.memory_candidates, self._last_user_message)
            # DeepSeek can legitimately omit optional metadata. Preserve explicit
            # "remember this" commands with the deterministic, policy-controlled
            # fallback without making a second model request.
            if not created and not parsed.turn.memory_candidates:
                created = self._memory_service.extract_from_message(self._last_user_message)
            self.last_memory_updates.extend(self._memory_service.memory_update(memory) for memory in created)

        # A user-visible fallback is still an assistant turn.  Persist it and
        # schedule extraction so a malformed visible reply never drops a useful
        # user fact such as a current goal.
        if self._should_persist_timeline():
            self._save_message(session_id, "assistant", parsed.payload["reply"], input_mode)
        if self._memory_service is not None:
            if self._memory_service.uses_background_extraction:
                created = self._memory_service.extract_high_precision_from_message(self._last_user_message)
                self.last_memory_updates.extend(self._memory_service.memory_update(memory) for memory in created)
            self._memory_service.schedule_extraction(self._last_user_message)

        self.last_turn = parsed.turn

        return parsed.payload

    async def stream_user_message(
        self, session_id: str, user_text: str,
        stored_reply_transform: Callable[[str], str] | None = None,
        input_mode: str = "text",
    ) -> AsyncIterator[str]:
        """Stream plain reply text and commit history only after clean completion."""
        context = self._context_manager.build(user_text).messages if self._context_manager else self._history.get_recent_messages(session_id, limit=self._history_limit)
        self.last_memory_updates = self._persist_user_message(session_id, user_text, input_mode)
        messages = [
            ChatMessage(role="system", content=character_live_prompt(self._persona)),
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
        if self._should_persist_timeline():
            self._save_message(session_id, "assistant", reply, input_mode)
        if self._memory_service is not None:
            if self._memory_service.uses_background_extraction:
                created = self._memory_service.extract_high_precision_from_message(self._last_user_message)
                self.last_memory_updates.extend(self._memory_service.memory_update(memory) for memory in created)
            self._memory_service.schedule_extraction(self._last_user_message)
        if (
            self._memory_service is not None
            and self._memory_service.llm_extraction_enabled
            and not self._memory_service.uses_background_extraction
        ):
            # Live mode streams plain speech rather than the JSON character
            # protocol. Preserve explicit memory commands after a completed
            # turn without adding a second DeepSeek request.
            created = self._memory_service.extract_from_message(self._last_user_message)
            self.last_memory_updates.extend(self._memory_service.memory_update(memory) for memory in created)

    def _persist_user_message(self, session_id: str, user_text: str, input_mode: str) -> list[dict[str, str]]:
        user_message = self._save_message(session_id, "user", user_text, input_mode)
        self._last_user_message = user_message
        if self._memory_service is None:
            return []
        if self._memory_service.llm_extraction_enabled:
            return []
        return [self._memory_service.memory_update(memory) for memory in self._memory_service.extract_from_message(user_message)]

    def _save_message(self, session_id: str, role: str, content: str, input_mode: str):
        if not self._should_persist_timeline():
            return None
        try:
            return self._history.save_message(session_id, role, content, input_mode=input_mode)
        except TypeError:
            # V0.4 test doubles and the legacy history implementation only expose three arguments.
            return self._history.save_message(session_id, role, content)

    def _should_persist_timeline(self) -> bool:
        return self._memory_service is None or self._memory_service.should_persist_timeline()

    @staticmethod
    def classify_intent(user_text: str) -> str:
        return classify_intent(user_text).value

    def _parse_response(
        self,
        raw_content: str,
        session_id: str | None = None,
        user_text: str = "",
    ) -> dict[str, str]:
        return self._parse_response_result(raw_content, session_id=session_id, user_text=user_text).payload

    def _parse_response_result(
        self,
        raw_content: str,
        session_id: str | None = None,
        user_text: str = "",
        empty_fallback_reply: str = "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз.",
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
            turn, valid_metadata, adapter_reason = parse_turn(payload, user_text=user_text)
        except ValueError:
            return self._fallback_response(
                raw_content,
                "schema_validation_error",
                session_id,
                empty_fallback_reply,
                event_type,
                report_invalid,
            )

        legacy_without_gesture = "gesture" not in payload and "affect" not in payload
        result_payload = legacy_result(turn, include_gesture=not legacy_without_gesture)
        nested_reply = self._extract_nested_reply(result_payload["reply"])
        if nested_reply is not None:
            turn = turn.model_copy(update={"reply": nested_reply})
            result_payload = legacy_result(turn, include_gesture=not legacy_without_gesture)

        if not valid_metadata:
            self._report_invalid_metadata(raw_content, adapter_reason or "invalid_metadata", session_id, event_type)
            return _ParseResult(result_payload, valid=True, reason=adapter_reason, turn=turn)
        return _ParseResult(result_payload, valid=True, reason=adapter_reason, turn=turn)

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

    def _report_invalid_metadata(self, raw_content: str, reason: str, session_id: str | None, event_type: str) -> None:
        logger.warning("Invalid Character Protocol metadata; reply retained: reason=%s raw_length=%s", reason, len(raw_content))
        if self._event_publisher is not None:
            metadata: dict[str, Any] = {"reason": reason, "raw_length": len(raw_content)}
            if session_id is not None:
                metadata["session_id"] = session_id
            self._event_publisher(event_type, "warning", "Invalid character metadata; reply retained", metadata)

    @staticmethod
    def _looks_like_structured_content(value: str) -> bool:
        return value.startswith(("{", "[", "```"))

    def _empty_model_fallback(self, _user_text: str) -> str:
        # Do not echo a potentially sensitive user message back into the UI.
        return "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз."
