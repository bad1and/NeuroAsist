# NeuroAsist Desktop Shell (Milestone 4)

The desktop shell is a Tauri 2 application around the existing React UI and FastAPI core. It starts the core on a randomly selected loopback port, injects an ephemeral token into the WebView before React starts, and terminates its managed child processes on exit.

## Development

```powershell
npm install --prefix apps/desktop
npm run dev --prefix apps/desktop
```

The dev shell uses the repository `.venv\Scripts\python.exe` when present and launches `python -m apps.backend.desktop_entry`. It starts Vite itself, so no browser tab or separately started backend is required. `CommandOrControl+Shift+N` opens the main window again; the tray provides the same action, Safe Mode, avatar toggle, and Quit.

Set `NEUROASIST_AVATAR_EXECUTABLE` to a Unity executable to make it an optional managed child. The shell gives it `NEUROASIST_BACKEND_URL` and `NEUROASIST_BACKEND_TOKEN`. Until the later overlay milestone adds a show/hide protocol, the tray avatar action stops or restarts that optional process.

## Safe Mode and recovery

Start the desktop binary with `--safe-mode` to skip Unity and backend model preloads. A crashed core is reported to the WebView and automatically receives one restart attempt; the `restart_core` Tauri command is available for a later in-UI recovery button.

## PyInstaller onedir spike

The initial packaging path is deliberately `--onedir`:

```powershell
.\apps\desktop\scripts\build-backend-onedir.ps1
```

For a packaged deployment, set `NEUROASIST_CORE_EXECUTABLE` to the generated `neuroasist-core.exe` before launching the shell. Shipping the executable as a Tauri external binary is deferred to the packaging milestone; this keeps the first desktop shell compatible with the local development runtime and avoids prematurely freezing a Windows installer layout.
