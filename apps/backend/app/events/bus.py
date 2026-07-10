import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AppEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    level: str
    message: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventBus:
    def __init__(self, max_events: int = 300) -> None:
        self._events: deque[AppEvent] = deque(maxlen=max_events)
        self._subscribers: set[asyncio.Queue[AppEvent]] = set()

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

        for queue in list(self._subscribers):
            self._put_event(queue, event)

        return event

    def get_recent_events(self, limit: int = 100) -> list[AppEvent]:
        safe_limit = max(0, min(limit, len(self._events)))
        return list(self._events)[-safe_limit:]

    def subscribe(self) -> asyncio.Queue[AppEvent]:
        queue: asyncio.Queue[AppEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AppEvent]) -> None:
        self._subscribers.discard(queue)

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
