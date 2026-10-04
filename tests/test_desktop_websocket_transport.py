from __future__ import annotations

import asyncio
import socket

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from apps.backend.desktop_entry import WEBSOCKET_PROTOCOL


def test_desktop_websocket_ping_during_concurrent_paused_writes(caplog) -> None:
    """Exercise the logged failure: pong while multiple sends await TCP drain."""

    async def scenario() -> None:
        app = FastAPI()
        connected = asyncio.Event()
        start_sends = asyncio.Event()
        sent = asyncio.Event()

        @app.websocket("/ws")
        async def endpoint(websocket: WebSocket) -> None:
            await websocket.accept()
            connected.set()
            try:
                await start_sends.wait()
                await asyncio.gather(
                    websocket.send_json({"type": "avatar.ping"}),
                    websocket.send_bytes(b"pcm-audio"),
                )
                sent.set()
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if message.get("text") is not None:
                        await websocket.send_text(message["text"])
                    elif message.get("bytes") is not None:
                        await websocket.send_bytes(message["bytes"])
            except WebSocketDisconnect:
                pass

        # An OS-assigned port keeps this isolated from the running desktop.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            config = uvicorn.Config(
                app,
                ws=WEBSOCKET_PROTOCOL,
                lifespan="off",
                log_config=None,
                timeout_graceful_shutdown=1,
            )
            server = uvicorn.Server(config)
            server_task = asyncio.create_task(server.serve(sockets=[listener]))
            paused_protocol = None
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        if server_task.done():
                            await server_task
                            raise AssertionError("WebSocket server stopped before startup")
                        await asyncio.sleep(0.01)
                    async with connect(
                        f"ws://127.0.0.1:{port}/ws", ping_interval=None, proxy=None,
                    ) as client:
                        await connected.wait()
                        paused_protocol = next(
                            protocol for protocol in server.server_state.connections
                            if isinstance(protocol, config.ws_protocol_class)
                        )
                        # Deterministically simulate a slow peer's full send
                        # buffer instead of relying on platform buffer sizes.
                        paused_protocol.pause_writing()
                        start_sends.set()
                        await asyncio.sleep(0)
                        await asyncio.sleep(0)
                        assert not sent.is_set()
                        pong = await client.ping(b"during-paused-writes")
                        await pong
                        assert not sent.is_set()
                        paused_protocol.resume_writing()
                        paused_protocol = None
                        await sent.wait()
                        messages = [await client.recv(), await client.recv()]
                        assert '{"type":"avatar.ping"}' in messages
                        assert b"pcm-audio" in messages
                        await client.send('{"type":"playback.finished"}')
                        assert await client.recv() == '{"type":"playback.finished"}'
                        await client.send(b"microphone-pcm")
                        assert await client.recv() == b"microphone-pcm"

                    # Reconnect after a normal client close, then shut down with
                    # an open socket, as the desktop does when it exits.
                    async with connect(
                        f"ws://127.0.0.1:{port}/ws", ping_interval=None, proxy=None,
                    ) as client:
                        await client.recv()
                        await client.recv()
                        pong = await client.ping(b"after-reconnect")
                        await pong
                        server.should_exit = True
                        await client.wait_closed()
                        assert client.close_code == 1012
                        await server_task
            finally:
                if paused_protocol is not None:
                    paused_protocol.resume_writing()
                start_sends.set()
                server.should_exit = True
                await asyncio.wait_for(server_task, timeout=5)

    asyncio.run(scenario())
    assert not [record for record in caplog.records if record.levelname == "ERROR"]
