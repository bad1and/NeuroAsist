# Milestone 4 — Tauri Desktop Shell

Milestone 4 turns the existing React panel and Python core into a desktop-owned runtime. It does not add long-term memory, semantic retrieval, Character Protocol v3, overlay rendering, VAD, or packaging release work from later milestones.

## Runtime ownership

`apps/desktop` contains a Tauri 2 shell with a native tray, single-instance handling, and the global shortcut `CommandOrControl+Shift+N` to reopen the control window. It creates the WebView programmatically only after Neuro Core is healthy, so the injected runtime configuration is available before React loads.

For each desktop run the shell:

1. reserves a random loopback port and generates a 256-bit token;
2. starts `python -m apps.backend.desktop_entry` (or `NEUROASIST_CORE_EXECUTABLE`);
3. passes the port, token, and optional Safe Mode through environment variables;
4. waits for authenticated `/health` before showing the main window;
5. starts the Unity executable only when `NEUROASIST_AVATAR_EXECUTABLE` is configured and Safe Mode is off.

React receives the loopback URL and token through a Tauri initialization script. HTTP requests send `X-NeuroAsist-Token`; event and voice WebSockets carry the one-run token as a query parameter. The backend enables that check only when `NEUROASIST_DESKTOP_TOKEN` is present, preserving the existing browser and test workflows.

## Lifecycle and recovery

The sidecar exposes an authenticated, desktop-only `/internal/shutdown` endpoint. On Tauri exit the shell requests it, allowing FastAPI to close the active episode and perform a bounded final summary pass, then waits briefly before terminating remaining children. The optional Unity child is stopped first.

The shell detects a core crash, reports it to the WebView with `desktop-core-status`, and performs one automatic restart. The `restart_core` Tauri command is available for an in-UI recovery control. `--safe-mode` disables the Unity child plus STT/TTS preloads. Until the later overlay milestone introduces a visual hide/show protocol, the tray avatar toggle stops or starts the optional Unity process.

## Development and packaging spike

See [apps/desktop/README.md](../apps/desktop/README.md) for the desktop development command and configuration. `apps/desktop/scripts/build-backend-onedir.ps1` is the required PyInstaller **onedir** spike; installer layout and shipping it as a Tauri external binary remain Milestone 10 work.

## Verification

`tests/test_desktop_auth.py` verifies authenticated desktop mode and unchanged browser mode. `scripts/smoke_desktop_core.ps1` starts the production sidecar entrypoint, verifies its authenticated health endpoint, and checks graceful shutdown. The web build verifies dynamic desktop credentials remain type-safe. The desktop project was additionally validated on Windows with MSVC Build Tools and Windows SDK: `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml` and `npx --prefix apps/desktop tauri build --debug --no-bundle` both complete successfully.
