"""Causal ownership of persisted conversation turns.

Routes and voice services may have different delivery mechanics, but none of
them may decide independently when a user message exists.  This coordinator
commits that fact first, then cancels an older generation, then leases the
assistant message which will receive streamed or batch output.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from apps.backend.app.storage.timeline import (
    AcceptedTimelineTurn,
    AssistantTimelineLease,
    StoredTimelineMessage,
    TimelineStore,
)


@dataclass(frozen=True)
class AcceptedTurn:
    session_id: str
    client_message_id: str | None
    user_message_id: str
    turn_id: str
    sequence_no: int
    generation: int
    utterance_id: str | None
    input_mode: str
    created: bool
    message: StoredTimelineMessage


@dataclass(frozen=True)
class AssistantLease:
    session_id: str
    assistant_message_id: str
    user_message_id: str
    turn_id: str
    generation: int
    utterance_id: str | None
    commit_policy: str
    message: StoredTimelineMessage


@dataclass
class _GenerationTask:
    task: asyncio.Task[Any]
    assistant_message_id: str | None = None


class ConversationTurnCoordinator:
    """One causal coordinator for text, upload and live conversation inputs."""

    def __init__(
        self,
        store: TimelineStore,
        event_publisher: Callable[[str, str, str, dict[str, object]], None] | None = None,
    ) -> None:
        self._store = store
        self._publish = event_publisher
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[tuple[str, int], _GenerationTask] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    async def accept_user_turn(
        self,
        *,
        session_id: str,
        content: str,
        input_mode: str,
        client_message_id: str | None = None,
        utterance_id: str | None = None,
        language: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AcceptedTurn:
        async with self._lock(session_id):
            accepted: AcceptedTimelineTurn = await asyncio.to_thread(
                self._store.accept_user_turn,
                session_key=session_id,
                content=content,
                input_mode=input_mode,
                client_message_id=client_message_id,
                utterance_id=utterance_id,
                language=language,
                metadata=metadata,
            )
            result = AcceptedTurn(
                session_id=session_id,
                client_message_id=client_message_id,
                user_message_id=accepted.message.id,
                turn_id=accepted.message.turn_id or "",
                sequence_no=accepted.message.sequence_no,
                generation=accepted.generation,
                utterance_id=utterance_id,
                input_mode=input_mode,
                created=accepted.created,
                message=accepted.message,
            )
            if not accepted.created:
                self._emit("turn.deduplicated", session_id, result)
                return result
            # The durable commit above is deliberately before this cancellation.
            await asyncio.to_thread(
                self._store.interrupt_stale_assistant_leases,
                session_key=session_id,
                generation=result.generation,
            )
            for (task_session, generation), record in list(self._tasks.items()):
                if task_session == session_id and generation < result.generation:
                    await self._interrupt_record(session_id, generation, record)
            self._emit("turn.accepted", session_id, result)
            return result

    async def begin_assistant(
        self, accepted: AcceptedTurn, *, commit_policy: str = "generated_text",
        metadata: dict[str, object] | None = None,
    ) -> AssistantLease:
        async with self._lock(accepted.session_id):
            lease: AssistantTimelineLease = await asyncio.to_thread(
                self._store.begin_assistant_turn,
                session_key=accepted.session_id,
                user_message_id=accepted.user_message_id,
                generation=accepted.generation,
                utterance_id=accepted.utterance_id,
                input_mode=accepted.input_mode,
                metadata=metadata,
            )
            return AssistantLease(
                session_id=accepted.session_id,
                assistant_message_id=lease.message.id,
                user_message_id=accepted.user_message_id,
                turn_id=accepted.turn_id,
                generation=accepted.generation,
                utterance_id=accepted.utterance_id,
                commit_policy=commit_policy,
                message=lease.message,
            )

    def register_generation_task(self, lease: AssistantLease, task: asyncio.Task[Any] | None = None) -> None:
        self._tasks[(lease.session_id, lease.generation)] = _GenerationTask(
            task=task or asyncio.current_task(), assistant_message_id=lease.assistant_message_id,
        )

    async def complete_assistant(self, session_id: str, lease: AssistantLease, content: str) -> StoredTimelineMessage:
        message = await asyncio.to_thread(
            self._store.finish_assistant_turn,
            session_key=session_id,
            assistant_message_id=lease.assistant_message_id,
            generation=lease.generation,
            content=content,
            status="completed",
        )
        self._tasks.pop((session_id, lease.generation), None)
        return message

    async def interrupt_assistant(self, session_id: str, lease: AssistantLease, prefix: str = "") -> StoredTimelineMessage:
        message = await asyncio.to_thread(
            self._store.finish_assistant_turn,
            session_key=session_id,
            assistant_message_id=lease.assistant_message_id,
            generation=lease.generation,
            content=prefix,
            status="interrupted",
        )
        self._tasks.pop((session_id, lease.generation), None)
        self._emit("assistant.interrupted", session_id, lease)
        return message

    async def fail_assistant(self, session_id: str, lease: AssistantLease) -> StoredTimelineMessage:
        message = await asyncio.to_thread(
            self._store.finish_assistant_turn,
            session_key=session_id,
            assistant_message_id=lease.assistant_message_id,
            generation=lease.generation,
            status="failed",
        )
        self._tasks.pop((session_id, lease.generation), None)
        return message

    async def cancel_session(self, session_id: str) -> None:
        """Invalidate all in-flight generations before the session store is cleared."""
        async with self._lock(session_id):
            for (task_session, generation), record in list(self._tasks.items()):
                if task_session == session_id:
                    await self._interrupt_record(session_id, generation, record)

    async def _interrupt_record(self, session_id: str, generation: int, record: _GenerationTask) -> None:
        if record.assistant_message_id:
            try:
                await asyncio.to_thread(
                    self._store.finish_assistant_turn,
                    session_key=session_id,
                    assistant_message_id=record.assistant_message_id,
                    generation=generation,
                    status="interrupted",
                )
            except (KeyError, RuntimeError):
                pass
        if not record.task.done():
            record.task.cancel()
        self._tasks.pop((session_id, generation), None)
        self._emit("turn.generation_cancelled", session_id, {"generation": generation})

    def _emit(self, event_type: str, session_id: str, value: object) -> None:
        if self._publish is None:
            return
        details: dict[str, object] = {"session_id": session_id}
        if isinstance(value, AcceptedTurn):
            details.update({"message_id": value.user_message_id, "turn_id": value.turn_id, "generation": value.generation})
        elif isinstance(value, AssistantLease):
            details.update({"message_id": value.assistant_message_id, "turn_id": value.turn_id, "generation": value.generation})
        elif isinstance(value, dict):
            details.update(value)
        self._publish(event_type, "info", event_type, details)
