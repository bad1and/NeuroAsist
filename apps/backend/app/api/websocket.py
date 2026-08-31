import asyncio
import contextlib
import logging
import json
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from apps.backend.app.avatar.protocol import AvatarProtocolError, parse_incoming

router = APIRouter()
logger = logging.getLogger(__name__)


def _desktop_token_is_valid(websocket: WebSocket, token: str | None) -> bool:
    expected_token = websocket.app.state.settings.desktop_auth_token
    return not expected_token or (token is not None and secrets.compare_digest(token, expected_token))


async def _session_is_active(websocket: WebSocket, session_id: str) -> bool:
    store = getattr(websocket.app.state, "timeline_store", None)
    if store is None:
        return True
    active_session_id = await asyncio.to_thread(store.active_session_id)
    return active_session_id in {None, session_id}


@router.websocket("/ws/avatar")
async def websocket_avatar(websocket: WebSocket, version: int = 1, token: str | None = None) -> None:
    if not _desktop_token_is_valid(websocket, token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if version not in {1, 2}:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    service = websocket.app.state.avatar_service
    if not service.enabled:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    client = await service.manager.register(websocket)
    service.event_bus.publish("avatar.connected", "info", "Avatar client connected", {"client_id": client.client_id})
    try:
        while True:
            try:
                raw = json.loads(await websocket.receive_text())
                envelope, payload = parse_incoming(raw)
            except json.JSONDecodeError:
                await service.protocol_error(client.client_id, "malformed_json", "Malformed JSON frame")
                continue
            except AvatarProtocolError as exc:
                await service.protocol_error(client.client_id, "protocol_error", str(exc))
                if "Unsupported protocol_version" in str(exc):
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break
                continue
            await service.inbound(client.client_id, envelope, payload)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        removed = await service.manager.unregister(client.client_id)
        if removed is not None:
            service.event_bus.publish("avatar.disconnected", "info", "Avatar client disconnected", {"client_id": client.client_id})


@router.websocket("/ws/voice/{session_id}")
async def websocket_voice(websocket: WebSocket, session_id: str, version: int = 1, token: str | None = None) -> None:
    if not _desktop_token_is_valid(websocket, token) or not await _session_is_active(websocket, session_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if version != 1:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    manager = websocket.app.state.voice_session_manager
    connection = await manager.register(session_id, websocket)
    shutdown_cancelled = False
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "voice.cancel":
                interrupt = getattr(websocket.app.state, "interrupt_voice_session", None)
                if callable(interrupt):
                    await interrupt(session_id, message.get("utterance_id"))
                else:
                    await manager.cancel(session_id, message.get("utterance_id"))
            elif message.get("type") == "playback.underrun":
                logger.info(
                    "Live playback underrun: session_id=%s utterance_id=%s playback_underrun_ms=%s",
                    session_id,
                    message.get("utterance_id"),
                    message.get("underrun_ms"),
                )
                websocket.app.state.event_bus.publish(
                    "voice.playback_underrun",
                    "warning",
                    "Live playback underrun",
                    {
                        "session_id": session_id,
                        "utterance_id": message.get("utterance_id"),
                        "underrun_ms": message.get("underrun_ms"),
                    },
                )
            elif message.get("type") == "playback.segment.decoded":
                websocket.app.state.event_bus.publish(
                    "voice.playback_segment_decoded",
                    "info",
                    "Live playback segment decoded",
                    {
                        "session_id": session_id,
                        "utterance_id": message.get("utterance_id"),
                        "segment_id": message.get("segment_id"),
                        "decode_ms": message.get("decode_ms"),
                    },
                )
            elif message.get("type") == "playback.started":
                websocket.app.state.event_bus.publish(
                    "voice.playback_started",
                    "info",
                    "Live playback started",
                    {
                        "session_id": session_id,
                        "utterance_id": message.get("utterance_id"),
                    },
                )
            elif message.get("type") == "playback.segment.started":
                service = getattr(websocket.app.state, "conversation_service", None)
                if service is not None:
                    await service.playback_segment_started(
                        session_id,
                        str(message.get("text", "")),
                        message.get("utterance_id"),
                        message.get("generation"),
                    )
            elif message.get("type") == "playback.segment.finished":
                service = getattr(websocket.app.state, "conversation_service", None)
                if service is not None:
                    await service.playback_segment_finished(
                        session_id,
                        message.get("text"),
                        message.get("utterance_id"),
                        message.get("generation"),
                    )
            elif message.get("type") == "playback.finished":
                service = getattr(websocket.app.state, "conversation_service", None)
                if service is not None:
                    await service.playback_finished(session_id, message.get("utterance_id"))
    except asyncio.CancelledError:
        shutdown_cancelled = True
        logger.info("Voice WebSocket closed during backend shutdown")
    except WebSocketDisconnect as exc:
        logger.info(
            "Live output WebSocket disconnected: session_id=%s code=%s",
            session_id,
            exc.code,
        )
    except RuntimeError as exc:
        logger.warning("Live output WebSocket failed: session_id=%s error=%s", session_id, exc)
    finally:
        unregister = manager.unregister(session_id, connection)
        if shutdown_cancelled:
            unregister = asyncio.wait_for(unregister, timeout=1.0)
        with contextlib.suppress(asyncio.CancelledError, RuntimeError, TimeoutError):
            await unregister


@router.websocket("/ws/voice-input/{session_id}")
async def websocket_voice_input(websocket: WebSocket, session_id: str, version: int = 3, token: str | None = None) -> None:
    if not _desktop_token_is_valid(websocket, token) or not await _session_is_active(websocket, session_id) or version != 3:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    manager = websocket.app.state.voice_input_session_manager
    connection = await manager.register(session_id, websocket, version=version)
    if connection.replaced_owner:
        # A previous input owner may already have handed its transcript to the
        # streaming LLM task before reconnect invalidated the STT lease. Cancel
        # that downstream generation before accepting audio from the new owner.
        interrupt = getattr(websocket.app.state, "interrupt_voice_session", None)
        if callable(interrupt):
            await interrupt(session_id, None)
        service = getattr(websocket.app.state, "conversation_service", None)
        if service is not None:
            await service.close_session(session_id)
    shutdown_cancelled = False
    graceful_stop = False
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await manager.feed(session_id, message["bytes"], connection)
                continue
            payload = json.loads(message.get("text") or "{}")
            if payload.get("type") == "voice.input.start":
                if payload.get("protocol_version", 3) != 3:
                    raise ValueError("voice input protocol v3 is required")
                if "mode" in payload:
                    raise ValueError("voice.input.start no longer accepts mode")
                await manager.start(
                    session_id,
                    sample_rate=int(payload.get("sample_rate", 16000)),
                    channels=int(payload.get("channels", 1)),
                    language=str(payload.get("language", "ru")),
                    audio_format=str(payload.get("format", "pcm_s16le")),
                    capture_profile=str(payload.get("capture_profile", "live")),
                    capture_settings=payload.get("capture_settings")
                    if isinstance(payload.get("capture_settings"), dict)
                    else {},
                    capture_constraints=payload.get("capture_constraints")
                    if isinstance(payload.get("capture_constraints"), dict)
                    else {},
                    capture_supported_constraints=payload.get("supported_constraints")
                    if isinstance(payload.get("supported_constraints"), dict)
                    else {},
                )
            elif payload.get("type") == "voice.input.stop":
                await manager.stop(session_id, connection=connection)
                graceful_stop = True
                break
    except asyncio.CancelledError:
        shutdown_cancelled = True
        logger.info("Voice input WebSocket closed during backend shutdown")
    except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        if not isinstance(exc, WebSocketDisconnect):
            with contextlib.suppress(Exception):
                await connection.send({"type": "voice.input.error", "message": str(exc)})
    finally:
        unregister = manager.unregister(
            session_id,
            connection,
            finalize_active=False,
        )
        if shutdown_cancelled:
            unregister = asyncio.shield(unregister)
        connection_is_current = False
        with contextlib.suppress(asyncio.CancelledError, RuntimeError):
            connection_is_current = await unregister
        service = getattr(websocket.app.state, "conversation_service", None)
        if connection_is_current:
            if not graceful_stop:
                interrupt = getattr(websocket.app.state, "interrupt_voice_session", None)
                if callable(interrupt):
                    with contextlib.suppress(Exception):
                        await interrupt(session_id, None)
            if service is not None:
                await service.close_session(session_id)


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket, token: str | None = None) -> None:
    if not _desktop_token_is_valid(websocket, token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    event_bus = websocket.app.state.event_bus
    queue = event_bus.subscribe()
    event_bus.publish(
        "backend.status",
        "info",
        "WebSocket client connected",
        {},
    )

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.model_dump())
    except asyncio.CancelledError:
        logger.info("Events WebSocket closed during backend shutdown")
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)
