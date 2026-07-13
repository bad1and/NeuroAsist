from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from .schemas import AvatarStatusClient


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AvatarClient:
    client_id: str
    websocket: WebSocket
    connected_at: datetime = field(default_factory=utc_now)
    last_heartbeat_at: datetime = field(default_factory=utc_now)
    client_name: str | None = None
    client_version: str | None = None
    platform: str | None = None
    state: str = "Idle"
    current_utterance_id: str | None = None
    current_motion_profile: str | None = None
    current_gesture: str | None = None

    def status(self) -> AvatarStatusClient:
        return AvatarStatusClient(
            client_id=self.client_id,
            connected_at=self.connected_at,
            last_heartbeat_at=self.last_heartbeat_at,
            client_name=self.client_name,
            client_version=self.client_version,
            platform=self.platform,
            state=self.state,
            current_utterance_id=self.current_utterance_id,
            current_motion_profile=self.current_motion_profile,
            current_gesture=self.current_gesture,
        )


@dataclass(frozen=True)
class BroadcastResult:
    attempted: int
    sent: int
    failed: int
    skipped: bool = False


class AvatarConnectionManager:
    """Small, broadcast-oriented manager which never holds a lock during I/O."""

    def __init__(self) -> None:
        self._clients: dict[str, AvatarClient] = {}
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> AvatarClient:
        client = AvatarClient(client_id=uuid4().hex, websocket=websocket)
        async with self._lock:
            self._clients[client.client_id] = client
        return client

    async def unregister(self, client_id: str) -> AvatarClient | None:
        async with self._lock:
            return self._clients.pop(client_id, None)

    async def get(self, client_id: str) -> AvatarClient | None:
        async with self._lock:
            return self._clients.get(client_id)

    async def update(self, client_id: str, **values: Any) -> None:
        async with self._lock:
            client = self._clients.get(client_id)
            if client is None:
                return
            for key, value in values.items():
                setattr(client, key, value)

    async def heartbeat(self, client_id: str) -> None:
        await self.update(client_id, last_heartbeat_at=utc_now())

    async def snapshot(self) -> list[AvatarClient]:
        async with self._lock:
            return list(self._clients.values())

    async def status_clients(self) -> list[AvatarStatusClient]:
        clients = await self.snapshot()
        return [client.status() for client in clients]

    async def broadcast(self, message: dict[str, Any]) -> BroadcastResult:
        clients = await self.snapshot()
        if not clients:
            return BroadcastResult(attempted=0, sent=0, failed=0)
        results = await asyncio.gather(
            *(self._send(client, message) for client in clients), return_exceptions=False
        )
        failed_ids = [client_id for client_id, sent in results if not sent]
        for client_id in failed_ids:
            await self.unregister(client_id)
        return BroadcastResult(
            attempted=len(clients), sent=len(clients) - len(failed_ids), failed=len(failed_ids)
        )

    async def send_to(self, client_id: str, message: dict[str, Any]) -> bool:
        client = await self.get(client_id)
        if client is None:
            return False
        _, sent = await self._send(client, message)
        if not sent:
            await self.unregister(client_id)
        return sent

    async def _send(self, client: AvatarClient, message: dict[str, Any]) -> tuple[str, bool]:
        try:
            await client.websocket.send_json(message)
            return client.client_id, True
        except Exception:
            return client.client_id, False

    async def stale_clients(self, timeout_seconds: float) -> list[AvatarClient]:
        now = utc_now()
        clients = await self.snapshot()
        stale = [
            client
            for client in clients
            if (now - client.last_heartbeat_at).total_seconds() > timeout_seconds
        ]
        removed: list[AvatarClient] = []
        for client in stale:
            item = await self.unregister(client.client_id)
            if item is not None:
                removed.append(item)
        return removed

    async def close(self) -> None:
        clients = await self.snapshot()
        for client in clients:
            try:
                await client.websocket.close()
            except Exception:
                pass
            await self.unregister(client.client_id)
