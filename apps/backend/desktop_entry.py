"""Production entrypoint used by the Tauri-managed Python sidecar."""

from __future__ import annotations

import os

# TeraTTS loads a bundled RUAccent vocabulary through ``Path.read_text()``.
# On Windows the interpreter encoding must be selected before importing the
# backend/model code; changing the environment later is too late.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

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
    # Reuse that already-constructed instance. Calling create_app() here built
    # a second complete service graph (and duplicated startup work) for every
    # desktop launch.
    from apps.backend.main import app

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
    try:
        server.run()
    except KeyboardInterrupt:
        # Ctrl+C in `npm run dev` is delivered to the whole Windows console
        # process group. Uvicorn has already run FastAPI shutdown handlers;
        # suppress the otherwise misleading traceback from asyncio.run().
        return


if __name__ == "__main__":
    main()
