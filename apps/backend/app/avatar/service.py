from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any
from collections.abc import Awaitable, Callable

from .connection_manager import AvatarConnectionManager, BroadcastResult
from .emotion_engine import EmotionEngine
from .schemas import (
    AvatarStatusResponse,
    AudioMutePayload,
    EmotionPayload,
    ErrorPayload,
    GesturePayload,
    OutgoingMessage,
    OverlayPayload,
    OverlayBoundsChangedPayload,
    PingPayload,
    SpeakPayload,
    StatePayload,
    StopPayload,
    StreamEndPayload,
    StreamMetadataPayload,
    StreamSegmentPayload,
    StreamStartPayload,
)
from apps.backend.app.schemas.character import Emotion, Gesture

logger = logging.getLogger(__name__)
PlaybackFinishedHandler = Callable[[str], Awaitable[None]]


class AvatarService:
    def __init__(
        self,
        manager: AvatarConnectionManager,
        event_bus,
        *,
        enabled: bool,
        heartbeat_interval_seconds: float,
        client_timeout_seconds: float,
        emotion_engine: EmotionEngine | None = None,
        overlay: OverlayPayload | None = None,
        audio_muted: bool = False,
        on_overlay_bounds_changed: Callable[[OverlayPayload], None] | None = None,
    ) -> None:
        self.manager = manager
        self.event_bus = event_bus
        self.enabled = enabled
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.client_timeout_seconds = client_timeout_seconds
        self.emotion_engine = emotion_engine or EmotionEngine()
        self.overlay = overlay or OverlayPayload()
        self.audio_muted = audio_muted
        self.on_overlay_bounds_changed = on_overlay_bounds_changed
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._playback_finished_handler: PlaybackFinishedHandler | None = None

    def bind_playback_finished_handler(
        self,
        handler: PlaybackFinishedHandler | None,
    ) -> None:
        self._playback_finished_handler = handler

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
        return AvatarStatusResponse(
            enabled=self.enabled,
            client_count=len(clients),
            clients=clients,
            emotion_engine=self.emotion_engine.status(),
        )

    async def speak(
        self, *, session_id: str, utterance_id: str, text: str, audio_url: str,
        emotion: str, intent: str, gesture: str = "auto", gesture_intensity: float = 1.0,
        interrupt: bool = True,
    ) -> BroadcastResult:
        state = self.emotion_engine.apply_metadata(
            emotion=Emotion(emotion), gesture=Gesture(gesture), intensity=gesture_intensity,
            utterance_id=utterance_id,
        )
        return await self._broadcast(
            "avatar.speak", session_id,
            SpeakPayload(utterance_id=utterance_id, text=text, audio_url=audio_url,
                         emotion=state.target_emotion, intent=intent, gesture=state.gesture,
                         gesture_intensity=state.intensity, interrupt=interrupt).model_dump(mode="json"),
            utterance_id=utterance_id,
        )

    async def set_emotion(self, *, session_id: str, emotion: str, intensity: float = 1.0) -> BroadcastResult:
        state = self.emotion_engine.apply_metadata(
            emotion=Emotion(emotion), gesture=Gesture.AUTO, intensity=intensity, utterance_id=None,
        )
        return await self._broadcast(
            "avatar.emotion", session_id,
            EmotionPayload(emotion=state.target_emotion, intensity=state.intensity).model_dump(mode="json"),
        )

    async def stop(self, *, session_id: str, utterance_id: str | None = None) -> BroadcastResult:
        self.emotion_engine.stop(utterance_id)
        return await self._broadcast(
            "avatar.stop", session_id, StopPayload(utterance_id=utterance_id).model_dump(mode="json"),
            utterance_id=utterance_id,
        )

    async def stream_start(
        self, *, session_id: str, utterance_id: str, intent: str, interrupt: bool = True
    ) -> BroadcastResult:
        return await self._broadcast(
            "avatar.stream.start",
            session_id,
            StreamStartPayload(
                utterance_id=utterance_id, intent=intent, interrupt=interrupt
            ).model_dump(mode="json"),
            utterance_id=utterance_id,
            protocol_version=2,
            min_protocol_version=2,
        )

    async def stream_segment(
        self,
        *,
        session_id: str,
        utterance_id: str,
        sequence: int,
        audio: bytes,
        duration_seconds: float,
        sample_rate: int = 24000,
        channels: int = 1,
        is_final: bool = False,
    ) -> BroadcastResult:
        return await self._broadcast(
            "avatar.stream.segment",
            session_id,
            StreamSegmentPayload(
                utterance_id=utterance_id,
                sequence=sequence,
                audio_base64=base64.b64encode(audio).decode("ascii"),
                sample_rate=sample_rate,
                channels=channels,
                duration_seconds=duration_seconds,
                is_final=is_final,
            ).model_dump(mode="json"),
            utterance_id=utterance_id,
            protocol_version=2,
            min_protocol_version=2,
        )

    async def stream_metadata(
        self, *, session_id: str, utterance_id: str, emotion: str, gesture: str, gesture_intensity: float
    ) -> BroadcastResult:
        state = self.emotion_engine.apply_metadata(
            emotion=Emotion(emotion), gesture=Gesture(gesture), intensity=gesture_intensity,
            utterance_id=utterance_id,
        )
        return await self._broadcast(
            "avatar.stream.metadata",
            session_id,
            StreamMetadataPayload(
                utterance_id=utterance_id,
                emotion=state.target_emotion,
                gesture=state.gesture,
                gesture_intensity=state.intensity,
            ).model_dump(mode="json"),
            utterance_id=utterance_id,
            protocol_version=2,
            min_protocol_version=2,
        )

    async def stream_end(self, *, session_id: str, utterance_id: str) -> BroadcastResult:
        return await self._broadcast(
            "avatar.stream.end",
            session_id,
            StreamEndPayload(utterance_id=utterance_id).model_dump(mode="json"),
            utterance_id=utterance_id,
            protocol_version=2,
            min_protocol_version=2,
        )

    async def gesture(
        self, *, session_id: str, gesture: str, intensity: float = 1.0, interrupt: bool = True
    ) -> BroadcastResult:
        state = self.emotion_engine.apply_gesture(Gesture(gesture), intensity=intensity, interrupt=interrupt)
        payload = GesturePayload(gesture=state.gesture, intensity=state.intensity, interrupt=interrupt)
        return await self._broadcast(
            "avatar.gesture", session_id, payload.model_dump(mode="json")
        )

    async def set_state(self, *, session_id: str, state: str) -> BroadcastResult:
        return await self._broadcast("avatar.state", session_id, StatePayload(state=state).model_dump(mode="json"))

    async def configure_overlay(self, overlay: OverlayPayload, *, session_id: str = "default") -> BroadcastResult:
        self.overlay = overlay
        return await self._broadcast(
            "avatar.overlay.configure", session_id, overlay.model_dump(mode="json"), protocol_version=2, min_protocol_version=2,
        )

    async def set_audio_muted(self, muted: bool, *, session_id: str = "default") -> BroadcastResult:
        self.audio_muted = muted
        return await self._broadcast(
            "avatar.audio.mute",
            session_id,
            AudioMutePayload(muted=muted).model_dump(mode="json"),
            protocol_version=2,
            min_protocol_version=2,
        )

    async def protocol_error(self, client_id: str, code: str, message: str) -> None:
        frame = OutgoingMessage(type="avatar.error", payload=ErrorPayload(code=code, message=message).model_dump(mode="json"))
        await self.manager.send_to(client_id, frame.model_dump(mode="json"))

    async def inbound(self, client_id: str, envelope, payload: object) -> None:
        await self.manager.heartbeat(client_id)
        if envelope.type == "avatar.hello":
            await self.manager.update(
                client_id, client_name=payload.client_name, client_version=payload.client_version,
                platform=payload.platform, protocol_version=envelope.protocol_version,
            )
            self.event_bus.publish("avatar.hello", "info", "Avatar client hello", {"client_id": client_id})
            frame = OutgoingMessage(
                protocol_version=2,
                type="avatar.overlay.configure",
                payload=self.overlay.model_dump(mode="json"),
            )
            await self.manager.send_to(client_id, frame.model_dump(mode="json"))
            audio_frame = OutgoingMessage(
                protocol_version=2,
                type="avatar.audio.mute",
                payload=AudioMutePayload(muted=self.audio_muted).model_dump(mode="json"),
            )
            await self.manager.send_to(client_id, audio_frame.model_dump(mode="json"))
            # Keep the persisted overlay as the final hello frame. Some Unity
            # clients apply the last configuration frame they receive after a
            # reconnect; the mute notification must not mask overlay state.
            await self.manager.send_to(client_id, frame.model_dump(mode="json"))
        elif envelope.type == "avatar.pong":
            return
        elif envelope.type == "avatar.ack":
            self.event_bus.publish("avatar.command_sent", "info", "Avatar command acknowledged", {"client_id": client_id, "message_id": payload.reply_to, "accepted": payload.accepted})
        elif envelope.type == "avatar.playback.started":
            await self.manager.update(client_id, current_utterance_id=payload.utterance_id, state="Speaking")
            self.event_bus.publish("avatar.speaking_started", "info", "Avatar playback started", {"client_id": client_id, "utterance_id": payload.utterance_id, "client_latency_ms": payload.client_latency_ms})
        elif envelope.type == "avatar.playback.finished":
            await self.manager.update(client_id, current_utterance_id=None, state="Idle")
            self.emotion_engine.stop(payload.utterance_id)
            self.event_bus.publish("avatar.speaking_finished", "info", "Avatar playback finished", {"client_id": client_id, "utterance_id": payload.utterance_id})
            if self._playback_finished_handler is not None:
                await self._playback_finished_handler(payload.utterance_id)
        elif envelope.type == "avatar.playback.failed":
            await self.manager.update(client_id, current_utterance_id=None, state="Error")
            self.emotion_engine.stop(payload.utterance_id)
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
        elif envelope.type == "avatar.stream.received":
            self.event_bus.publish(
                "avatar.stream_segment_received",
                "info",
                "Avatar stream segment received",
                {"client_id": client_id, **payload.model_dump(mode="json")},
            )
        elif envelope.type == "avatar.overlay.bounds_changed":
            self.overlay = self.overlay.model_copy(update=payload.model_dump())
            if self.on_overlay_bounds_changed is not None:
                self.on_overlay_bounds_changed(self.overlay)
            self.event_bus.publish("avatar.overlay_bounds_changed", "info", "Avatar overlay position updated", {"client_id": client_id, **payload.model_dump(mode="json")})

    async def _broadcast(
        self,
        message_type: str,
        session_id: str,
        payload: dict[str, Any],
        *,
        utterance_id: str | None = None,
        protocol_version: int = 1,
        min_protocol_version: int = 1,
    ) -> BroadcastResult:
        if not self.enabled:
            return BroadcastResult(attempted=0, sent=0, failed=0, skipped=True)
        frame = OutgoingMessage(
            protocol_version=protocol_version,
            type=message_type,
            session_id=session_id,
            payload=payload,
        )
        result = await self.manager.broadcast(
            frame.model_dump(mode="json"), min_protocol_version=min_protocol_version
        )
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
