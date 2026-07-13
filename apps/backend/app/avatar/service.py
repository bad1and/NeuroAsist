from __future__ import annotations

import asyncio
import logging
from typing import Any

from .connection_manager import AvatarConnectionManager, BroadcastResult
from .schemas import (
    AvatarStatusResponse,
    EmotionPayload,
    ErrorPayload,
    GesturePayload,
    OutgoingMessage,
    PingPayload,
    SpeakPayload,
    StatePayload,
    StopPayload,
)

logger = logging.getLogger(__name__)


class AvatarService:
    def __init__(
        self,
        manager: AvatarConnectionManager,
        event_bus,
        *,
        enabled: bool,
        heartbeat_interval_seconds: float,
        client_timeout_seconds: float,
    ) -> None:
        self.manager = manager
        self.event_bus = event_bus
        self.enabled = enabled
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.client_timeout_seconds = client_timeout_seconds
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.enabled and self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def close(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        await self.manager.close()

    async def status(self) -> AvatarStatusResponse:
        clients = await self.manager.status_clients()
        return AvatarStatusResponse(enabled=self.enabled, client_count=len(clients), clients=clients)

    async def speak(
        self, *, session_id: str, utterance_id: str, text: str, audio_url: str,
        emotion: str, intent: str, gesture: str = "auto", gesture_intensity: float = 1.0,
        interrupt: bool = True,
    ) -> BroadcastResult:
        return await self._broadcast(
            "avatar.speak", session_id,
            SpeakPayload(utterance_id=utterance_id, text=text, audio_url=audio_url,
                         emotion=emotion, intent=intent, gesture=gesture,
                         gesture_intensity=gesture_intensity, interrupt=interrupt).model_dump(mode="json"),
            utterance_id=utterance_id,
        )

    async def set_emotion(self, *, session_id: str, emotion: str, intensity: float = 1.0) -> BroadcastResult:
        return await self._broadcast(
            "avatar.emotion", session_id,
            EmotionPayload(emotion=emotion, intensity=intensity).model_dump(mode="json"),
        )

    async def stop(self, *, session_id: str, utterance_id: str | None = None) -> BroadcastResult:
        return await self._broadcast(
            "avatar.stop", session_id, StopPayload(utterance_id=utterance_id).model_dump(mode="json"),
            utterance_id=utterance_id,
        )

    async def gesture(
        self, *, session_id: str, gesture: str, intensity: float = 1.0, interrupt: bool = True
    ) -> BroadcastResult:
        payload = GesturePayload(gesture=gesture, intensity=intensity, interrupt=interrupt)
        return await self._broadcast(
            "avatar.gesture", session_id, payload.model_dump(mode="json")
        )

    async def set_state(self, *, session_id: str, state: str) -> BroadcastResult:
        return await self._broadcast("avatar.state", session_id, StatePayload(state=state).model_dump(mode="json"))

    async def protocol_error(self, client_id: str, code: str, message: str) -> None:
        frame = OutgoingMessage(type="avatar.error", payload=ErrorPayload(code=code, message=message).model_dump(mode="json"))
        await self.manager.send_to(client_id, frame.model_dump(mode="json"))

    async def inbound(self, client_id: str, envelope, payload: object) -> None:
        await self.manager.heartbeat(client_id)
        if envelope.type == "avatar.hello":
            await self.manager.update(
                client_id, client_name=payload.client_name, client_version=payload.client_version,
                platform=payload.platform,
            )
            self.event_bus.publish("avatar.hello", "info", "Avatar client hello", {"client_id": client_id})
        elif envelope.type == "avatar.pong":
            return
        elif envelope.type == "avatar.ack":
            self.event_bus.publish("avatar.command_sent", "info", "Avatar command acknowledged", {"client_id": client_id, "message_id": payload.reply_to, "accepted": payload.accepted})
        elif envelope.type == "avatar.playback.started":
            await self.manager.update(client_id, current_utterance_id=payload.utterance_id, state="Speaking")
            self.event_bus.publish("avatar.speaking_started", "info", "Avatar playback started", {"client_id": client_id, "utterance_id": payload.utterance_id})
        elif envelope.type == "avatar.playback.finished":
            await self.manager.update(client_id, current_utterance_id=None, state="Idle")
            self.event_bus.publish("avatar.speaking_finished", "info", "Avatar playback finished", {"client_id": client_id, "utterance_id": payload.utterance_id})
        elif envelope.type == "avatar.playback.failed":
            await self.manager.update(client_id, current_utterance_id=None, state="Error")
            self.event_bus.publish("avatar.playback_failed", "warning", "Avatar playback failed", {"client_id": client_id, "utterance_id": payload.utterance_id, "reason": payload.reason})
        elif envelope.type == "avatar.state.changed":
            await self.manager.update(client_id, state=payload.state)
            self.event_bus.publish("avatar.state_changed", "info", "Avatar state changed", {"client_id": client_id, "state": payload.state})
        elif envelope.type == "avatar.gesture.started":
            await self.manager.update(client_id, current_gesture=payload.gesture)
            self.event_bus.publish(envelope.type, "info", "Avatar motion event", {"client_id": client_id, **payload.model_dump(mode="json")})
        elif envelope.type in {"avatar.gesture.finished", "avatar.gesture.failed"}:
            await self.manager.update(client_id, current_gesture=None)
            self.event_bus.publish(envelope.type, "info", "Avatar motion event", {"client_id": client_id, **payload.model_dump(mode="json")})
        elif envelope.type == "avatar.motion_profile_changed":
            await self.manager.update(client_id, current_motion_profile=payload.profile)
            self.event_bus.publish(envelope.type, "info", "Avatar motion event", {"client_id": client_id, **payload.model_dump(mode="json")})

    async def _broadcast(self, message_type: str, session_id: str, payload: dict[str, Any], *, utterance_id: str | None = None) -> BroadcastResult:
        if not self.enabled:
            return BroadcastResult(attempted=0, sent=0, failed=0, skipped=True)
        frame = OutgoingMessage(type=message_type, session_id=session_id, payload=payload)
        result = await self.manager.broadcast(frame.model_dump(mode="json"))
        event_data = {"message_id": frame.message_id, "command_type": message_type, "utterance_id": utterance_id, "attempted": result.attempted, "sent": result.sent, "failed": result.failed}
        self.event_bus.publish(
            "avatar.command_failed" if result.failed else "avatar.command_sent",
            "warning" if result.failed else "info",
            "Avatar command dispatched",
            event_data,
        )
        return result

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval_seconds)
                stale = await self.manager.stale_clients(self.client_timeout_seconds)
                for client in stale:
                    self.event_bus.publish("avatar.heartbeat_timeout", "warning", "Avatar heartbeat timed out", {"client_id": client.client_id})
                    self.event_bus.publish("avatar.disconnected", "info", "Avatar client disconnected", {"client_id": client.client_id})
                await self._broadcast("avatar.ping", "default", PingPayload().model_dump(mode="json"))
        except asyncio.CancelledError:
            raise
