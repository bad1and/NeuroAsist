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
    if not _desktop_token_is_valid(websocket, token):
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
                await manager.cancel(session_id, message.get("utterance_id"))
            elif message.get("type") == "playback.underrun":
                logger.info(
                    "Live playback underrun: session_id=%s utterance_id=%s playback_underrun_ms=%s",
                    session_id,
                    message.get("utterance_id"),
                    message.get("underrun_ms"),
                )
    except asyncio.CancelledError:
        shutdown_cancelled = True
        logger.info("Voice WebSocket closed during backend shutdown")
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        unregister = manager.unregister(session_id, connection)
        if shutdown_cancelled:
            unregister = asyncio.wait_for(unregister, timeout=1.0)
        with contextlib.suppress(asyncio.CancelledError, RuntimeError, TimeoutError):
            await unregister


@router.websocket("/ws/voice-input/{session_id}")
async def websocket_voice_input(websocket: WebSocket, session_id: str, version: int = 1, token: str | None = None) -> None:
    if not _desktop_token_is_valid(websocket, token) or version != 1:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    manager = websocket.app.state.voice_input_session_manager
    connection = await manager.register(session_id, websocket)
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await manager.feed(session_id, message["bytes"])
                continue
            payload = json.loads(message.get("text") or "{}")
            if payload.get("type") == "voice.input.start":
                await manager.start(
                    session_id,
                    sample_rate=int(payload.get("sample_rate", 16000)),
                    channels=int(payload.get("channels", 1)),
                    language=str(payload.get("language", "ru")),
                )
            elif payload.get("type") == "voice.input.stop":
                break
    except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        if not isinstance(exc, WebSocketDisconnect):
            with contextlib.suppress(Exception):
                await connection.send({"type": "voice.input.error", "message": str(exc)})
    finally:
        await manager.unregister(session_id, connection)


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
