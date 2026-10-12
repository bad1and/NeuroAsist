"""Production entrypoint used by the Tauri-managed Python sidecar."""

from __future__ import annotations

import json
import os
import sys

# TeraTTS loads a bundled RUAccent vocabulary through ``Path.read_text()``.
# On Windows the interpreter encoding must be selected before importing the
# backend/model code; changing the environment later is too late.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
os.environ.setdefault("KMP_BLOCKTIME", "0")
# Desktop readiness owns loading feedback. Hub progress bars assume a console
# and can fail while flushing inherited Windows GUI handles.
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

import uvicorn
from fastapi import FastAPI


GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5
# The legacy websockets transport can race concurrent writes with ping/pong
# while its TCP buffer is paused. SansIO uses Uvicorn's own flow control.
WEBSOCKET_PROTOCOL = "websockets-sansio"


def configure_standard_streams() -> None:
    """Keep model/library diagnostics from depending on a live parent console."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            if stream is None:
                raise ValueError("No console stream")
            stream.flush()
            stream.write("")
        except (OSError, ValueError):
            # Application diagnostics still go to the configured UTF-8 log.
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def load_runtime_credentials() -> None:
    """Read one credential payload from the desktop shell's anonymous pipe."""
    if os.getenv("NEUROASIST_CREDENTIALS_STDIN") != "1":
        return
    raw = sys.stdin.buffer.readline(65_537)
    if not raw or len(raw) > 65_536:
        raise RuntimeError("Desktop credential payload is missing or too large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Desktop credential payload is invalid") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Desktop credential payload must be an object")

    from apps.backend.app.core.config import configure_runtime_credentials

    configure_runtime_credentials(
        deepseek_api_key=_optional_string(payload.get("deepseek_api_key")),
        coding_api_key=_optional_string(payload.get("coding_api_key")),
        search_api_keys={p: _optional_string(payload.get(f"{p}_api_key")) for p in ("brave", "tavily", "serper")},
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("Desktop credential values must be strings")
    return value


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
    configure_standard_streams()
    from pathlib import Path
    from apps.backend.app.storage.recovery import maintenance_main, recover_interrupted_restore
    if maintenance_main(sys.argv[1:]):
        return
    if root := os.getenv("NEUROASIST_APP_DATA_DIR"):
        recover_interrupted_restore(Path(root))
    configure_safe_mode()
    load_runtime_credentials()
    port = int(os.getenv("NEUROASIST_PORT", "8000"))
    app = create_desktop_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        log_config=None,
        ws=WEBSOCKET_PROTOCOL,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    )
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
