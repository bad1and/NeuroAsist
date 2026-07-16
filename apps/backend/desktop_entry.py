"""Production entrypoint used by the Tauri-managed Python sidecar."""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from apps.backend.main import create_app


def create_desktop_app() -> FastAPI:
    app = create_app()

    @app.post("/internal/shutdown", include_in_schema=False)
    async def request_graceful_shutdown() -> dict[str, str]:
        app.state.desktop_shutdown_callback()
        return {"status": "stopping"}

    return app


def main() -> None:
    if os.getenv("NEUROASIST_SAFE_MODE") == "1":
        os.environ["AVATAR_ENABLED"] = "false"
        os.environ["VOICE_PRELOAD_STT_MODEL"] = "false"
        os.environ["VOICE_PRELOAD_TTS_MODEL"] = "false"
    port = int(os.getenv("NEUROASIST_PORT", "8000"))
    app = create_desktop_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    app.state.desktop_shutdown_callback = lambda: setattr(server, "should_exit", True)
    try:
        server.run()
    except KeyboardInterrupt:
        # Ctrl+C in `npm run dev` is delivered to the whole Windows console
        # process group. Uvicorn has already run FastAPI shutdown handlers;
        # suppress the otherwise misleading traceback from asyncio.run().
        return


if __name__ == "__main__":
    main()
