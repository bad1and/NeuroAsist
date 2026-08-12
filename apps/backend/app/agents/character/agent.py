import asyncio
import json
import logging
import re
from difflib import SequenceMatcher
from functools import lru_cache
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Callable

from apps.backend.app.agents.character.prompts import (
    CHARACTER_REPAIR_PROMPT,
    character_json_prompt,
    character_live_prompt,
)
from apps.backend.app.agents.character.persona import get_persona
from apps.backend.app.agents.character.protocol import classify_intent, legacy_result, parse_turn
from apps.backend.app.agents.character.voice_input import (
    VoiceInputInterpretation,
    VoiceInputInterpreter,
)
from apps.backend.app.llm.base import ChatMessage, LLMProvider
from apps.backend.app.schemas.character import CharacterTurn
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from apps.backend.app.conversation.behavior import BehaviorGuide


@dataclass(frozen=True)
class _ParseResult:
    payload: dict[str, Any]
    valid: bool
    reason: str | None = None
    turn: CharacterTurn | None = None


# A single turn normalises the same `previous_assistant_reply` and `user_text`
# from several guard predicates in a row, and the regex walks every character
# each time. The cache only has to span those few calls, so it is kept small
# rather than growing into an accidental transcript of the conversation.
@lru_cache(maxsize=32)
def _normalize_for_similarity(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.lower(), flags=re.UNICODE))


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
        coding_bridge=None,
    ) -> None:
        self._llm_provider = llm_provider
        self._history = history
        self._history_limit = history_limit
        self._event_publisher = event_publisher
        self._context_manager = context_manager
        self._memory_service = memory_service
        self._voice_input = VoiceInputInterpreter(memory_service)
        self._persona = get_persona(persona_name)
        self._coding_bridge = coding_bridge
        self.last_turn: CharacterTurn | None = None
        self.last_memory_updates: list[dict[str, str]] = []
        self._last_user_message = None
        self._active_turn_id: str | None = None

    def _prepare_turn(
        self,
        session_id: str,
        user_text: str,
        input_mode: str,
        *,
        source_message=None,
        raw_user_text: str | None = None,
        voice_corrections: tuple[dict[str, object], ...] = (),
    ):
        """Perform synchronous persistence/context work outside the event loop."""
        interpreted = (
            VoiceInputInterpretation(user_text, len(voice_corrections), voice_corrections)
            if input_mode == "voice" and raw_user_text is not None
            else self._voice_input.interpret(user_text, input_mode)
        )
        effective_text = interpreted.text
        if source_message is None:
            self.last_memory_updates = self._persist_user_message(
                session_id,
                raw_user_text if raw_user_text is not None else user_text,
                input_mode,
                interpreted,
            )
        else:
            # The route/coordinator owns durable acceptance.  The agent only
            # consumes that source message to construct causal context.
            self._last_user_message = source_message
            if interpreted.changed:
                apply_interpretation = getattr(self._history, "apply_voice_interpretation", None)
                if callable(apply_interpretation):
                    self._last_user_message = apply_interpretation(
                        source_message.id,
                        interpreted.text,
                        interpreted.replacement_count,
                        list(interpreted.replacements),
                    )
            self._active_turn_id = getattr(source_message, "turn_id", None)
            self.last_memory_updates = []
        if self._memory_service is not None:
            resolved = self._memory_service.resolve_clarification_response(
                self._last_user_message,
            )
            self.last_memory_updates.extend(
                self._memory_service.memory_update(memory)
                for memory in resolved
            )
            self._memory_service.prepare_clarification_from_message(
                self._last_user_message,
            )
        built_context = (
            self._context_manager.build(
                effective_text,
                session_id=session_id,
                current_message_id=getattr(self._last_user_message, "id", None),
            )
            if self._context_manager
            else None
        )
        return interpreted, effective_text, built_context

    async def handle_user_message(
        self,
        session_id: str,
        user_text: str,
        input_mode: str = "text",
        *,
        source_message=None,
        persist_reply: bool = True,
        persist_reply_callback: Callable[[str], Any] | None = None,
        state_context: str | None = None,
        state_behavior: "BehaviorGuide | None" = None,
        raw_user_text: str | None = None,
        voice_corrections: tuple[dict[str, object], ...] = (),
    ) -> dict[str, Any]:
        interpreted, effective_text, built_context = await asyncio.to_thread(
            self._prepare_turn,
            session_id,
            user_text,
            input_mode,
            source_message=source_message,
            raw_user_text=raw_user_text,
            voice_corrections=voice_corrections,
        )
        prompt_user_text = (
            built_context.effective_user_text
            if built_context is not None and built_context.effective_user_text
            else effective_text
        )
        coding_context = (
            self._coding_bridge.observe_user_message(session_id, effective_text, self._last_user_message)
            if self._coding_bridge is not None
            else None
        )
        if coding_context:
            state_context = "\n\n".join(part for part in (state_context, f"CODING AGENT COORDINATION:\n{coding_context}") if part)
        required_anchors = self._required_response_anchors(prompt_user_text)
        if built_context is not None:
            built_context.diagnostics["relevance_guard"] = {
                "outcome": "not_required",
                "required_anchors": required_anchors,
            }
        context = built_context.messages if built_context is not None else self._history.get_recent_messages(session_id, limit=self._history_limit)
        pending_followup = bool(built_context and built_context.diagnostics.get("pending_direct_message_count"))
        response_target_text = built_context.response_target_text if built_context is not None else None
        response_target_anchors = (
            list(built_context.response_target_anchors)
            if built_context is not None
            else []
        )
        previous_assistant_reply = self._previous_assistant_reply(context)
        previous_assistant_id = (
            str(built_context.diagnostics.get("previous_assistant_message_id"))
            if built_context and built_context.diagnostics.get("previous_assistant_message_id")
            else None
        )
        messages = [
            ChatMessage(role="system", content=character_json_prompt(self._persona, state_context)),
            *context,
            ChatMessage(role="user", content=prompt_user_text),
        ]
        empty_reply = self._empty_model_fallback(prompt_user_text)

        llm_response = await self._llm_provider.generate(messages)
        parsed = self._parse_response_result(
            llm_response.content,
            session_id=session_id,
            user_text=prompt_user_text,
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
                user_text=prompt_user_text,
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

        needs_continuity_retry = parsed.valid and (
            self._has_unconfirmed_continuity_accusation(parsed.payload["reply"])
            or self._has_unconfirmed_assistant_content_attribution(
                parsed.payload["reply"], previous_assistant_reply, prompt_user_text,
            )
        )
        needs_pending_retry = (
            parsed.valid
            and pending_followup
            and self._appears_to_ignore_response_target(
                parsed.payload["reply"],
                response_target_anchors,
            )
        )
        needs_anchor_retry = parsed.valid and self._misses_required_anchors(parsed.payload["reply"], required_anchors)
        needs_status_grounding_retry = parsed.valid and self._has_ungrounded_status_question(
            parsed.payload["reply"], prompt_user_text,
        )
        duplicate = self._stale_duplicate_assessment(
            parsed.payload["reply"] if parsed.valid else "", previous_assistant_reply, prompt_user_text,
        )
        needs_duplicate_retry = bool(parsed.valid and duplicate["stale"])
        if needs_continuity_retry or needs_pending_retry or needs_anchor_retry or needs_duplicate_retry or needs_status_grounding_retry:
            if built_context is not None:
                built_context.diagnostics["relevance_guard"] = {
                    "outcome": "detected",
                    "reason": "missing_anchor" if needs_anchor_retry else "continuity",
                    "required_anchors": required_anchors,
                }
            # This is deliberately invisible: a snarky but ungrounded opening
            # is worse than one extra model pass, and must not reach TTS.
            self._publish_relevance_guard(
                "detected", previous_assistant_id, duplicate, pending_followup,
                    "missing_anchor" if needs_anchor_retry else "stale_duplicate" if needs_duplicate_retry else "ungrounded_status" if needs_status_grounding_retry else "continuity",
            )
            try:
                guarded = await self._llm_provider.generate([
                    *messages,
                    ChatMessage(
                        role="system",
                        content=self._guard_retry_instruction(
                            needs_pending_retry,
                            needs_duplicate_retry,
                            needs_status_grounding_retry,
                            required_anchors,
                            response_target_text,
                            response_target_anchors,
                        ),
                    ),
                ])
                repaired = self._parse_response_result(
                    guarded.content, session_id=session_id, user_text=prompt_user_text,
                    empty_fallback_reply=empty_reply, report_invalid=False,
                )
            except Exception:
                repaired = None
            if (
                repaired is not None
                and repaired.valid
                and not self._has_unconfirmed_continuity_accusation(repaired.payload["reply"])
                and not self._has_unconfirmed_assistant_content_attribution(
                    repaired.payload["reply"], previous_assistant_reply, prompt_user_text,
                )
                and (
                    not pending_followup
                    or not self._appears_to_ignore_response_target(
                        repaired.payload["reply"],
                        response_target_anchors,
                    )
                )
                and not self._misses_required_anchors(repaired.payload["reply"], required_anchors)
                and not self._stale_duplicate_assessment(repaired.payload["reply"], previous_assistant_reply, prompt_user_text)["stale"]
                and not self._has_ungrounded_status_question(repaired.payload["reply"], prompt_user_text)
            ):
                parsed = repaired
                if built_context is not None:
                    built_context.diagnostics["relevance_guard"]["outcome"] = "applied"
                self._publish_relevance_guard("applied", previous_assistant_id, duplicate, pending_followup, "retry_accepted")
            elif needs_anchor_retry or needs_duplicate_retry or needs_status_grounding_retry or needs_pending_retry:
                parsed = (
                    self._anchor_reply_fallback(required_anchors)
                    if needs_anchor_retry
                    else self._status_reply_fallback()
                    if needs_status_grounding_retry
                    else self._response_target_fallback(response_target_text or "")
                    if needs_pending_retry
                    else self._stale_reply_fallback()
                )
                if built_context is not None:
                    built_context.diagnostics["relevance_guard"]["outcome"] = "fallback"
                self._publish_relevance_guard("fallback", previous_assistant_id, duplicate, pending_followup, "retry_rejected")

        if parsed.turn is not None and state_behavior is not None and state_behavior.expression_strength != "muted":
            parsed = self._arbitrate_presentation(parsed, state_behavior)

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
        elif (
            not parsed.valid
            and self._memory_service is not None
            and self._memory_service.llm_extraction_enabled
            and not self._memory_service.uses_background_extraction
        ):
            created = self._memory_service.extract_from_message(self._last_user_message)
            self.last_memory_updates.extend(self._memory_service.memory_update(memory) for memory in created)

        # A user-visible fallback is still an assistant turn.  Persist it and
        # schedule extraction so a malformed visible reply never drops a useful
        # user fact such as a current goal.
        if persist_reply_callback is not None:
            assistant_message = persist_reply_callback(parsed.payload["reply"])
        elif self._should_persist_timeline() and persist_reply:
            assistant_message = self._save_message(
                session_id, "assistant", parsed.payload["reply"], input_mode,
                turn_id=self._active_turn_id, reply_to_message_id=getattr(self._last_user_message, "id", None),
            )
        else:
            assistant_message = None
        if self._memory_service is not None:
            if self._memory_service.uses_background_extraction:
                created = self._memory_service.extract_high_precision_from_message(self._last_user_message)
                self.last_memory_updates.extend(self._memory_service.memory_update(memory) for memory in created)
            self._memory_service.schedule_extraction(assistant_message)

        self.last_turn = parsed.turn

        return parsed.payload

    async def stream_user_message(
        self, session_id: str, user_text: str,
        stored_reply_transform: Callable[[str], str] | None = None,
        input_mode: str = "text",
        source_message=None,
        state_context: str | None = None,
        schedule_memory: bool = True,
        persist_reply: bool | None = None,
        raw_user_text: str | None = None,
        voice_corrections: tuple[dict[str, object], ...] = (),
    ) -> AsyncIterator[str]:
        """Stream plain reply text and commit history only after clean completion."""
        interpreted, effective_text, built_context = await asyncio.to_thread(
            self._prepare_turn,
            session_id,
            user_text,
            input_mode,
            source_message=source_message,
            raw_user_text=raw_user_text,
            voice_corrections=voice_corrections,
        )
        prompt_user_text = (
            built_context.effective_user_text
            if built_context is not None and built_context.effective_user_text
            else effective_text
        )
        coding_context = (
            self._coding_bridge.observe_user_message(session_id, effective_text, self._last_user_message)
            if self._coding_bridge is not None
            else None
        )
        if coding_context:
            state_context = "\n\n".join(part for part in (state_context, f"CODING AGENT COORDINATION:\n{coding_context}") if part)
        required_anchors = self._required_response_anchors(prompt_user_text)
        if built_context is not None:
            built_context.diagnostics["relevance_guard"] = {
                "outcome": "not_required",
                "required_anchors": required_anchors,
            }
        context = built_context.messages if built_context is not None else self._history.get_recent_messages(session_id, limit=self._history_limit)
        pending_followup = bool(built_context and built_context.diagnostics.get("pending_direct_message_count"))
        response_target_text = built_context.response_target_text if built_context is not None else None
        response_target_anchors = (
            list(built_context.response_target_anchors)
            if built_context is not None
            else []
        )
        previous_assistant_reply = self._previous_assistant_reply(context)
        previous_assistant_id = (
            str(built_context.diagnostics.get("previous_assistant_message_id"))
            if built_context and built_context.diagnostics.get("previous_assistant_message_id")
            else None
        )
        system_prompt = character_live_prompt(self._persona, state_context)
        messages = [
            ChatMessage(role="system", content=system_prompt),
            *context,
            ChatMessage(role="user", content=prompt_user_text),
        ]
        chunks: list[str] = []
        async for delta in self._guarded_live_stream(
            messages,
            require_pending_response=pending_followup,
            previous_assistant_reply=previous_assistant_reply,
            previous_assistant_id=previous_assistant_id,
            user_text=prompt_user_text,
            required_anchors=required_anchors,
            response_target_text=response_target_text,
            response_target_anchors=response_target_anchors,
            guard_diagnostics=built_context.diagnostics if built_context is not None else None,
        ):
            if not delta:
                continue
            chunks.append(delta)
            yield delta
        reply = "".join(chunks).strip()
        if stored_reply_transform is not None:
            reply = stored_reply_transform(reply)
        if not reply:
            reply = self._empty_model_fallback(effective_text)
            yield reply
        if persist_reply is None:
            persist_reply = source_message is None
        if self._should_persist_timeline() and persist_reply:
            assistant_message = self._save_message(
                session_id, "assistant", reply, input_mode,
                turn_id=self._active_turn_id, reply_to_message_id=getattr(self._last_user_message, "id", None),
            )
        else:
            assistant_message = None
        if self._memory_service is not None and schedule_memory:
            if self._memory_service.uses_background_extraction:
                created = self._memory_service.extract_high_precision_from_message(self._last_user_message)
                self.last_memory_updates.extend(self._memory_service.memory_update(memory) for memory in created)
            self._memory_service.schedule_extraction(assistant_message)
        if (
            schedule_memory
            and
            self._memory_service is not None
            and self._memory_service.llm_extraction_enabled
            and not self._memory_service.uses_background_extraction
        ):
            # Live mode streams plain speech rather than the JSON character
            # protocol. Preserve explicit memory commands after a completed
            # turn without adding a second DeepSeek request.
            created = self._memory_service.extract_from_message(self._last_user_message)
            self.last_memory_updates.extend(self._memory_service.memory_update(memory) for memory in created)

    def _persist_user_message(self, session_id: str, user_text: str, input_mode: str, interpreted) -> list[dict[str, str]]:
        user_message = self._save_message(session_id, "user", user_text, input_mode)
        self._active_turn_id = getattr(user_message, "turn_id", None)
        if user_message is not None and interpreted.changed:
            apply_interpretation = getattr(self._history, "apply_voice_interpretation", None)
            if callable(apply_interpretation):
                user_message = apply_interpretation(
                    user_message.id,
                    interpreted.text,
                    interpreted.replacement_count,
                    list(interpreted.replacements),
                )
        self._last_user_message = user_message
        if self._memory_service is None:
            return []
        if self._memory_service.llm_extraction_enabled:
            return []
        return [self._memory_service.memory_update(memory) for memory in self._memory_service.extract_from_message(user_message)]

    def _save_message(
        self, session_id: str, role: str, content: str, input_mode: str,
        *, turn_id: str | None = None, reply_to_message_id: str | None = None,
    ):
        if not self._should_persist_timeline():
            return None
        try:
            return self._history.save_message(
                session_id, role, content, input_mode=input_mode,
                turn_id=turn_id, reply_to_message_id=reply_to_message_id,
            )
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
    def _arbitrate_presentation(parsed: _ParseResult, guide: "BehaviorGuide") -> _ParseResult:
        """Canonical state wins over optional model metadata; visible text is untouched."""
        from apps.backend.app.schemas.character import AffectCue, DeliveryCue, Emotion, Gesture, GestureCue
        assert parsed.turn is not None
        gesture_name = next((name for name in guide.allowed_gestures if name in Gesture._value2member_map_), "auto")
        turn = parsed.turn.model_copy(update={
            "affect": AffectCue(emotion=Emotion(guide.avatar_emotion), intensity=guide.avatar_intensity),
            "gesture": GestureCue(name=Gesture(gesture_name), intensity=guide.avatar_intensity),
            "delivery": DeliveryCue(pace=guide.tts_pace, emphasis=guide.tts_emphasis),
        })
        return _ParseResult(legacy_result(turn), valid=parsed.valid, reason=parsed.reason, turn=turn)

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

    async def _guarded_live_stream(
        self, messages: list[ChatMessage], *, require_pending_response: bool = False,
        previous_assistant_reply: str = "", previous_assistant_id: str | None = None,
        user_text: str = "", required_anchors: list[str] | None = None,
        response_target_text: str | None = None,
        response_target_anchors: list[str] | None = None,
        guard_diagnostics: dict[str, object] | None = None,
    ) -> AsyncIterator[str]:
        """Reject continuity or stale-repetition failures before UI/TTS sees text."""
        buffered: list[str] = []
        released = False
        status_check = self._is_casual_status_check(user_text)
        # Both depend only on the fixed arguments, so they are resolved once per
        # turn rather than per delta: `_user_allows_repetition` runs a
        # SequenceMatcher over the whole previous reply, and the buffering loop
        # used to repeat it for every chunk before the first word reached TTS.
        allows_repetition = self._user_allows_repetition(user_text, previous_assistant_reply)
        duplicate_guard = bool(previous_assistant_reply and not allows_repetition)
        async for delta in self._llm_provider.stream(messages):
            if released:
                yield delta
                continue
            buffered.append(delta)
            opening = "".join(buffered)
            # A bare greeting often ends the first sentence ("Ну? Я здесь.")
            # and the actual accusation follows immediately. Extend the hold
            # only for that suspicious opener; ordinary streaming keeps its
            # original first-sentence latency and delta cadence.
            sentence_count = len(re.findall(r"[.!?…](?:\s|$)", opening))
            suspicious_opener = bool(re.search(r"(?:^|\n)\s*(?:ну|а)\?\s*(?:я\s+здесь)?", opening.lower()))
            required_sentences = 3 if status_check else 2 if suspicious_opener or require_pending_response or duplicate_guard or required_anchors else 1
            if sentence_count < required_sentences and len(opening) < 220:
                continue
            duplicate = self._stale_duplicate_assessment(opening, previous_assistant_reply, user_text)
            if self._has_unconfirmed_continuity_accusation(opening) or self._has_unconfirmed_assistant_content_attribution(
                opening, previous_assistant_reply, user_text,
            ) or (
                require_pending_response
                and self._appears_to_ignore_response_target(
                    opening,
                    response_target_anchors or [],
                )
            ) or self._misses_required_anchors(opening, required_anchors or []) or duplicate["stale"] or self._has_ungrounded_status_question(opening, user_text):
                reason = (
                    "missing_anchor" if self._misses_required_anchors(opening, required_anchors or [])
                    else "stale_duplicate" if duplicate["stale"]
                    else "ungrounded_status" if self._has_ungrounded_status_question(opening, user_text)
                    else "continuity"
                )
                self._publish_relevance_guard("detected", previous_assistant_id, duplicate, require_pending_response, reason)
                if guard_diagnostics is not None:
                    guard_diagnostics["relevance_guard"] = {
                        "outcome": "detected", "reason": reason,
                        "required_anchors": required_anchors or [],
                    }
                retry = await self._live_guard_retry(
                    messages,
                    previous_assistant_reply,
                    user_text,
                    require_pending_response,
                    required_anchors or [],
                    response_target_text,
                    response_target_anchors or [],
                )
                if retry == self._stale_reply_fallback().payload["reply"]:
                    self._publish_relevance_guard("fallback", previous_assistant_id, duplicate, require_pending_response, "retry_rejected")
                else:
                    self._publish_relevance_guard("applied", previous_assistant_id, duplicate, require_pending_response, "retry_accepted")
                if guard_diagnostics is not None:
                    guard_diagnostics["relevance_guard"]["outcome"] = "applied"
                yield retry
                return
            released = True
            yield opening
        if not released and buffered:
            opening = "".join(buffered)
            duplicate = self._stale_duplicate_assessment(opening, previous_assistant_reply, user_text)
            if self._has_unconfirmed_continuity_accusation(opening) or self._has_unconfirmed_assistant_content_attribution(
                opening, previous_assistant_reply, user_text,
            ) or (
                require_pending_response
                and self._appears_to_ignore_response_target(
                    opening,
                    response_target_anchors or [],
                )
            ) or self._misses_required_anchors(opening, required_anchors or []) or duplicate["stale"] or self._has_ungrounded_status_question(opening, user_text):
                reason = (
                    "missing_anchor" if self._misses_required_anchors(opening, required_anchors or [])
                    else "stale_duplicate" if duplicate["stale"]
                    else "ungrounded_status" if self._has_ungrounded_status_question(opening, user_text)
                    else "continuity"
                )
                self._publish_relevance_guard("detected", previous_assistant_id, duplicate, require_pending_response, reason)
                if guard_diagnostics is not None:
                    guard_diagnostics["relevance_guard"] = {
                        "outcome": "detected", "reason": reason,
                        "required_anchors": required_anchors or [],
                    }
                retry = await self._live_guard_retry(
                    messages,
                    previous_assistant_reply,
                    user_text,
                    require_pending_response,
                    required_anchors or [],
                    response_target_text,
                    response_target_anchors or [],
                )
                if guard_diagnostics is not None:
                    guard_diagnostics["relevance_guard"]["outcome"] = "applied"
                yield retry
            else:
                yield opening

    async def _live_guard_retry(
        self, messages: list[ChatMessage], previous_assistant_reply: str,
        user_text: str, require_pending_response: bool, required_anchors: list[str],
        response_target_text: str | None = None,
        response_target_anchors: list[str] | None = None,
    ) -> str:
        """A retry is fully buffered so a second stale answer cannot reach TTS."""
        try:
            chunks = [
                delta async for delta in self._llm_provider.stream([
                    *messages,
                    ChatMessage(
                        role="system",
                        content=self._guard_retry_instruction(
                            require_pending_response,
                            True,
                            self._is_casual_status_check(user_text),
                            required_anchors,
                            response_target_text,
                            response_target_anchors or [],
                        ),
                    ),
                ])
            ]
        except Exception:
            return self._stale_reply_fallback().payload["reply"]
        reply = "".join(chunks).strip()
        if (
            not reply
            or self._has_unconfirmed_continuity_accusation(reply)
            or self._has_unconfirmed_assistant_content_attribution(reply, previous_assistant_reply, user_text)
            or (
                require_pending_response
                and self._appears_to_ignore_response_target(
                    reply,
                    response_target_anchors or [],
                )
            )
            or self._misses_required_anchors(reply, required_anchors)
            or self._stale_duplicate_assessment(reply, previous_assistant_reply, user_text)["stale"]
            or self._has_ungrounded_status_question(reply, user_text)
        ):
            if required_anchors:
                return self._anchor_reply_fallback(required_anchors).payload["reply"]
            if require_pending_response:
                return self._response_target_fallback(
                    response_target_text or "",
                ).payload["reply"]
            if self._is_casual_status_check(user_text):
                return self._status_reply_fallback().payload["reply"]
            return self._stale_reply_fallback().payload["reply"]
        return reply

    @staticmethod
    def _has_unconfirmed_continuity_accusation(reply: str) -> bool:
        return bool(re.search(
            r"\b(?:ты\s+(?:опять|снова)\s+(?:начал|повторяешь|забыл)|"
            r"(?:опять|снова)\s+зов[её]шь|"
            r"я\s+уже\s+(?:сказала|говорила)|(?:снова|опять)\s+начал\s+(?:разговор|заново)|"
            r"заинтриговал\s+и\s+замолчал)",
            reply.lower(),
        ))

    @classmethod
    def _has_unconfirmed_assistant_content_attribution(
        cls, reply: str, previous_assistant_reply: str, user_text: str,
    ) -> bool:
        """Reject hallucinations that attribute Iris's example to the user.

        A criticism often refers to a detail Iris introduced one turn ago.
        Mentioning that detail is fine when Iris owns it; it becomes a
        continuity error only when the reply simultaneously says that the user
        asked for/said that assistant-only detail.
        """
        if not previous_assistant_reply:
            return False
        normalized_reply = reply.lower().replace("ё", "е")
        attribution = re.search(
            r"\b(?:ты\s+)?(?:сам\s+)?(?:попросил|просил|хотел|сказал|назвал|принес|выдал)\b",
            normalized_reply,
        )
        if attribution is None:
            return False
        assistant_terms = cls._content_stems(previous_assistant_reply)
        user_terms = cls._content_stems(user_text)
        reply_terms = cls._content_stems(reply)
        # Four/five-character stems deliberately handle normal Russian
        # inflection (ёжик/ёжика, скелеты/скелетами) without pretending to be
        # a semantic parser.  The attribution phrase keeps this conservative.
        assistant_only = assistant_terms - user_terms
        return bool(assistant_only & reply_terms)

    @staticmethod
    def _content_stems(value: str) -> set[str]:
        stop_words = {
            "когда", "котор", "этот", "этим", "этого", "вообще", "потом", "сам", "сама",
            "попрос", "просил", "хотел", "сказал", "назвал", "была", "было", "были",
            "тебе", "тебя", "твой", "твоя", "моей", "моя", "своей", "свою", "только",
            "анекд", "шутк", "бред", "какая", "какой", "полная", "следую",
        }
        words = re.findall(r"[^\W_]+", value.lower().replace("ё", "е"), flags=re.UNICODE)
        stop_stems = {word[:4] for word in stop_words}
        return {
            word[:4]
            for word in words
            if len(word) >= 4 and word[:4] not in stop_stems
        }

    @staticmethod
    def _appears_to_ignore_pending_followup(reply: str) -> bool:
        opening = reply.lower().strip()[:240]
        return bool(
            re.search(r"\b(?:опять|снова)\s+зов[её]шь\b", opening)
            or "есть что сказать" in opening
            or re.fullmatch(r"(?:ну[!?., ]*|да[!?., ]*)?(?:я\s+)?(?:здесь|слушаю|говори)[.!?… ]*", opening)
        )

    @classmethod
    def _appears_to_ignore_response_target(
        cls,
        reply: str,
        target_anchors: list[str],
    ) -> bool:
        if cls._appears_to_ignore_pending_followup(reply):
            return True
        normalized = reply.casefold().replace("ё", "е")
        reply_stems = {
            word[:6]
            for word in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
            if len(word) >= 5
        }
        topical_overlap = bool(reply_stems & set(target_anchors))
        wake_only_opening = bool(re.search(
            r"(?iu)(?:^|[.!?…]\s*)(?:ну[,.!?… ]*)?(?:я\s+)?"
            r"(?:здесь|слушаю|говори)\b|"
            r"\b(?:снова|опять)\s+ищешь\b|"
            r"\b(?:что[- ]?то\s+решил|ищешь\s+свою\s+задачу)\b",
            reply,
        ))
        return bool(target_anchors and wake_only_opening and not topical_overlap)

    @staticmethod
    def _required_response_anchors(user_text: str) -> list[str]:
        normalized = user_text.lower().replace("ё", "е")
        anchors: list[str] = []
        for match in re.finditer(
            r"\bзовут\s+([a-zа-я][a-zа-я-]{1,30})\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            anchors.append(match.group(1))
        if len(normalized) <= 60:
            for match in re.finditer(
                r"\bне\s+[a-zа-я][a-zа-я-]{1,30}\s*,?\s*а\s+([a-zа-я][a-zа-я-]{1,30})\s*[.!?…]*$",
                normalized,
                flags=re.IGNORECASE,
            ):
                anchors.append(match.group(1))
        if re.search(r"\b(?:запомни|запомнить|помни)\b", normalized):
            content_words = [
                word for word in re.findall(r"[a-zа-я][a-zа-я-]{3,}", normalized)
                if word not in {"запомни", "запомнить", "пожалуйста", "теперь", "будешь"}
            ]
            anchors.extend(content_words[-2:])
        return list(dict.fromkeys(anchors))

    @staticmethod
    def _misses_required_anchors(reply: str, anchors: list[str]) -> bool:
        if not anchors:
            return False
        normalized = " ".join(re.findall(r"[a-zа-я0-9]+", reply.lower().replace("ё", "е")))
        return any(anchor.lower().replace("ё", "е") not in normalized for anchor in anchors)

    @staticmethod
    def _is_casual_status_check(user_text: str) -> bool:
        normalized = user_text.lower().replace("ё", "е")
        return bool(re.search(
            r"\b(?:как\s+(?:дела|делишки)|как\s+ты|че\s+как|что\s+как)\b",
            normalized,
        ))

    @classmethod
    def _has_ungrounded_status_question(cls, reply: str, user_text: str) -> bool:
        """Reject invented personal specifics in a greeting/status exchange."""
        if not cls._is_casual_status_check(user_text):
            return False
        questions = [
            item.strip(" \n\t.!?…")
            for item in re.findall(r"[^.!?…？]+[?？]", reply.lower().replace("ё", "е"))
        ]
        safe = re.compile(
            r"(?iu)^(?:а\s+)?(?:"
            r"у\s+тебя\s+как|как\s+у\s+тебя|как\s+(?:ты|сам|сама|дела|настроение)|"
            r"что\s+(?:у\s+тебя\s+)?нового|чем\s+занимаешься|как\s+день"
            r")\b"
        )
        return any(question and safe.search(question) is None for question in questions)

    @staticmethod
    def _guard_retry_instruction(
        require_pending_response: bool,
        stale_duplicate: bool = False,
        status_grounding: bool = False,
        required_anchors: list[str] | None = None,
        response_target_text: str | None = None,
        response_target_anchors: list[str] | None = None,
    ) -> str:
        instruction = CharacterAgent._continuity_retry_instruction()
        if stale_duplicate:
            instruction += (
                " Твой черновик слишком похож на предыдущий ответ Iris. Не повторяй его "
                "и ответь на новую последнюю реплику пользователя по существу."
            )
        if require_pending_response:
            instruction += (
                " Пользователь только позвал тебя после неотвеченной прямой реплики: "
                "содержательно ответь на эту реплику, а не на само обращение по имени."
            )
            if response_target_text:
                instruction += (
                    " Реплика, на которую нужно ответить: "
                    f"«{response_target_text[:1000]}»."
                )
            if response_target_anchors:
                instruction += (
                    " Не теряй её тему; ориентиры: "
                    + ", ".join(response_target_anchors)
                    + "."
                )
        if status_grounding:
            instruction += (
                " Пользователь лишь спросил, как у Iris дела. Не придумывай ему конкретные "
                "занятия, происшествия, игры, начальника, поломки или проблемы. Ответь о себе "
                "и, если нужно, задай только нейтральный вопрос вроде «А у тебя как дела?»."
            )
        if required_anchors:
            instruction += (
                " Обязательно явно отреагируй на последнюю содержательную часть всего блока "
                f"и упомяни смысловые якоря: {', '.join(required_anchors)}."
            )
        return instruction

    @staticmethod
    def _previous_assistant_reply(context: list[ChatMessage]) -> str:
        return next((message.content for message in reversed(context) if message.role == "assistant"), "")

    @staticmethod
    def _normalized_for_similarity(value: str) -> str:
        return _normalize_for_similarity(value)

    @classmethod
    def _user_allows_repetition(cls, user_text: str, previous_assistant_reply: str) -> bool:
        normalized = cls._normalized_for_similarity(user_text)
        if any(marker in normalized for marker in ("повтори", "повтор", "процитируй", "цитат", "перескажи", "пересказ")):
            return True
        previous = cls._normalized_for_similarity(previous_assistant_reply)
        return (
            len(normalized) >= 40
            and len(previous) >= 40
            and SequenceMatcher(None, normalized, previous).ratio() >= 0.82
        )

    @classmethod
    def _stale_duplicate_assessment(
        cls, candidate: str, previous_assistant_reply: str, user_text: str,
    ) -> dict[str, object]:
        candidate_normalized = cls._normalized_for_similarity(candidate)
        previous_normalized = cls._normalized_for_similarity(previous_assistant_reply)
        if not candidate_normalized or not previous_normalized or cls._user_allows_repetition(user_text, previous_assistant_reply):
            return {"stale": False, "similarity": 0.0, "reason": "exempt_or_empty"}
        shorter = min(len(candidate_normalized), len(previous_normalized))
        similarity = SequenceMatcher(None, candidate_normalized, previous_normalized).ratio()
        exact = candidate_normalized == previous_normalized and shorter >= 24
        repeated_prefix = (
            shorter >= 96
            and (candidate_normalized in previous_normalized or previous_normalized in candidate_normalized)
        )
        near_duplicate = shorter >= 120 and similarity >= 0.90
        return {
            "stale": exact or repeated_prefix or near_duplicate,
            "similarity": round(similarity, 4),
            "reason": "exact" if exact else "prefix" if repeated_prefix else "near_duplicate" if near_duplicate else "distinct",
        }

    def _publish_relevance_guard(
        self, outcome: str, previous_assistant_id: str | None, assessment: dict[str, object],
        pending_followup: bool, reason: str,
    ) -> None:
        if self._event_publisher is None:
            return
        self._event_publisher(
            "llm.relevance_guard",
            "warning" if outcome in {"detected", "fallback"} else "info",
            "LLM response relevance guard evaluated",
            {
                "outcome": outcome,
                "reason": reason,
                "previous_assistant_message_id": previous_assistant_id,
                "similarity": assessment.get("similarity", 0.0),
                "similarity_reason": assessment.get("reason"),
                "pending_followup": pending_followup,
            },
        )

    @staticmethod
    def _stale_reply_fallback() -> _ParseResult:
        return _ParseResult(
            {"reply": "Похоже, я зациклилась на прошлом ответе. Не хочу повторять его вместо реакции на твоё сообщение.", "emotion": "neutral", "intent": "unknown"},
            valid=False,
            reason="stale_duplicate_retry_failed",
        )

    @staticmethod
    def _anchor_reply_fallback(anchors: list[str]) -> _ParseResult:
        rendered = ", ".join(anchor.capitalize() for anchor in anchors)
        return _ParseResult(
            {
                "reply": f"Поняла и не пропустила главное: {rendered}. Запомню.",
                "emotion": "neutral",
                "intent": "acknowledge",
            },
            valid=False,
            reason="required_anchor_retry_failed",
        )

    @staticmethod
    def _status_reply_fallback() -> _ParseResult:
        return _ParseResult(
            {
                "reply": "У меня всё нормально, я здесь и слушаю. А у тебя как дела?",
                "emotion": "neutral",
                "intent": "casual_chat",
            },
            valid=False,
            reason="ungrounded_status_retry_failed",
        )

    @staticmethod
    def _response_target_fallback(target_text: str) -> _ParseResult:
        normalized = target_text.casefold().replace("ё", "е")
        if "модел" in normalized or "посовет" in normalized:
            reply = (
                "Я вижу твой предыдущий вопрос о том, какую модель я советовала, "
                "но сейчас не могу уверенно восстановить название и не хочу выдумывать."
            )
        else:
            reply = (
                "Я прочитала предыдущую реплику, но не смогла уверенно восстановить "
                "ответ по существу. Лучше уточни её, чтобы я не ответила мимо."
            )
        return _ParseResult(
            {
                "reply": reply,
                "emotion": "neutral",
                "intent": "clarify",
            },
            valid=False,
            reason="response_target_retry_failed",
        )

    @staticmethod
    def _continuity_retry_instruction() -> str:
        return (
            "Переформулируй ответ без обвинений пользователя в повторе, забывчивости "
            "или смене темы: они не подтверждены контекстом. Не приписывай пользователю "
            "детали из предыдущего ответа Iris как его собственные слова или запрос. "
            "Продолжи тему предыдущего завершённого хода либо коротко уточни связь."
        )

    def _empty_model_fallback(self, _user_text: str) -> str:
        # Do not echo a potentially sensitive user message back into the UI.
        return "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз."
