import asyncio
import itertools
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

# Events are published several times per TTS segment on the live voice path, so
# the identifier is a process-scoped counter rather than a fresh uuid4 per
# event. Consumers only use `id` as a map/React key and for de-duplication.
_ID_PREFIX = uuid4().hex[:8]
_ID_COUNTER = itertools.count(1)


@dataclass(slots=True)
class AppEvent:
    """Plain payload holder.

    Deliberately not a pydantic model: nothing validates these events, they are
    constructed on the hot path, and the only consumers call `model_dump()` or
    read attributes. `EventResponse` still validates them at the HTTP boundary.
    """

    type: str
    level: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"{_ID_PREFIX}-{next(_ID_COUNTER)}")
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "level": self.level,
            "message": self.message,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class EventBus:
    def __init__(self, max_events: int = 300) -> None:
        self._events: deque[AppEvent] = deque(maxlen=max_events)
        # Each subscriber queue is owned by the loop that created it, so a
        # publish from a worker thread can hand the item back to that loop
        # instead of touching the queue directly.
        self._subscribers: dict[
            asyncio.Queue[AppEvent], asyncio.AbstractEventLoop | None
        ] = {}
        self._subscriber_lock = threading.Lock()

    def publish(
        self,
        event_type: str,
        level: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> AppEvent:
        event = AppEvent(
            type=event_type,
            level=level,
            message=message,
            metadata=metadata or {},
        )
        self._events.append(event)

        if not self._subscribers:
            return event

        with self._subscriber_lock:
            targets = list(self._subscribers.items())
        try:
            running_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        for queue, owner_loop in targets:
            if owner_loop is None or owner_loop is running_loop:
                self._put_event(queue, event)
                continue
            if owner_loop.is_closed():
                continue
            try:
                owner_loop.call_soon_threadsafe(self._put_event, queue, event)
            except RuntimeError:
                # The loop shut down between the check and the hand-off.
                continue

        return event

    def get_recent_events(self, limit: int = 100) -> list[AppEvent]:
        safe_limit = max(0, min(limit, len(self._events)))
        return list(self._events)[-safe_limit:]

    def subscribe(self) -> asyncio.Queue[AppEvent]:
        queue: asyncio.Queue[AppEvent] = asyncio.Queue(maxsize=100)
        try:
            owner_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            owner_loop = None
        with self._subscriber_lock:
            self._subscribers[queue] = owner_loop
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AppEvent]) -> None:
        with self._subscriber_lock:
            self._subscribers.pop(queue, None)

    def _put_event(self, queue: asyncio.Queue[AppEvent], event: AppEvent) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass
