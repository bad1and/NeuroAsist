"""Content-free active conversation time, shared by text and voice delivery."""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import RLock
from typing import Callable

from apps.backend.app.storage.timeline import TimelineStore


class ConversationUsageTracker:
    IDLE_SECONDS = 300
    CHECKPOINT_SECONDS = 15

    def __init__(self, store: TimelineStore, *, paused: bool = False, clock: Callable[[], float] = time.monotonic) -> None:
        self._store = store
        self._clock = clock
        self._lock = RLock()
        self._paused = paused
        self._seconds = 0.0
        self._started_at: str | None = None
        self._last_tick = clock()
        self._deadline: float | None = None
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._started_at is not None:
                return
            saved = self._store.conversation_usage()
            self._seconds = float(saved["active_seconds"])
            self._started_at = str(saved["tracking_started_at"])
            self._last_tick = self._clock()
            # Never resume a previous process's active interval or count downtime.
            self._deadline = None

    def _advance(self) -> float:
        now = self._clock()
        if self._deadline is not None and not self._paused:
            self._seconds += max(0.0, min(now, self._deadline) - self._last_tick)
        self._last_tick = now
        return now

    def record_activity(self, event_id: str) -> None:
        with self._lock:
            if self._started_at is None or self._closed or self._paused or event_id in self._seen:
                return
            now = self._advance()
            self._seen[event_id] = None
            if len(self._seen) > 4096:
                self._seen.popitem(last=False)
            self._deadline = now + self.IDLE_SECONDS

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._advance()
            self._paused = paused
            # Leaving incognito requires a fresh real turn before counting again.
            self._deadline = None

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            if self._started_at is None:
                raise RuntimeError("Conversation usage is not ready")
            self._advance()
            return {"active_seconds": int(self._seconds), "tracking_started_at": self._started_at}

    def checkpoint(self) -> None:
        with self._lock:
            if self._started_at is None:
                return
            self._advance()
            self._store.save_conversation_usage(self._seconds)

    def close(self) -> None:
        with self._lock:
            self.checkpoint()
            self._deadline = None
            self._closed = True
