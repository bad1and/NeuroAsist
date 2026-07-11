import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/voice/{session_id}")
async def websocket_voice(websocket: WebSocket, session_id: str, version: int = 1) -> None:
    if version != 1:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    manager = websocket.app.state.voice_session_manager
    connection = await manager.register(session_id, websocket)
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
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await manager.unregister(session_id, connection)


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
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
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)
