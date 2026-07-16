"""Production entrypoint used by the Tauri-managed Python sidecar."""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI


def configure_safe_mode() -> None:
    """Apply desktop-safe overrides before the backend settings are imported."""
    if os.getenv("NEUROASIST_SAFE_MODE") == "1":
        os.environ["AVATAR_ENABLED"] = "false"
        os.environ["VOICE_PRELOAD_STT_MODEL"] = "false"
        os.environ["VOICE_PRELOAD_TTS_MODEL"] = "false"


def create_desktop_app() -> FastAPI:
    # ``apps.backend.main`` constructs its compatibility ASGI app at import time,
    # which also caches Settings. Import it only after safe-mode environment
    # overrides have been applied by ``main``.
    from apps.backend.main import create_app

    app = create_app()

    @app.post("/internal/shutdown", include_in_schema=False)
    async def request_graceful_shutdown() -> dict[str, str]:
        app.state.desktop_shutdown_callback()
        return {"status": "stopping"}

    return app


def main() -> None:
    configure_safe_mode()
    port = int(os.getenv("NEUROASIST_PORT", "8000"))
    app = create_desktop_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    app.state.desktop_shutdown_callback = lambda: setattr(server, "should_exit", True)
    server.run()


if __name__ == "__main__":
    main()
