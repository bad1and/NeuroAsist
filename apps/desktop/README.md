# Iris Desktop Shell (Milestone 4)

The desktop shell is a Tauri 2 application around the existing React UI and FastAPI core. It starts the core on a randomly selected loopback port, injects an ephemeral token into the WebView before React starts, and terminates its managed child processes on exit.

## Development

```powershell
npm install --prefix apps/desktop
npm install --prefix apps/web
```

Start the companion with one command:

```powershell
npm --prefix apps/desktop run dev
```

The shell starts Vite and `python -m apps.backend.desktop_entry` itself, so no separate backend process or browser tab is required. If Windows asks `Terminate batch job (Y/N)?` after `Ctrl+C`, answer `Y`; the shell then stops the managed backend cleanly.

The Unity Editor path is needed only when rebuilding the avatar renderer:

```powershell
$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\<version>\Editor\Unity.exe'
npm --prefix apps/desktop run build:avatar
```

Replace `<version>` with the installed Unity version or use the full path to your `Unity.exe`. The environment variable applies only to the current PowerShell session and must be set again in a new terminal.

The dev shell uses the repository `.venv\Scripts\python.exe` when present. `CommandOrControl+Shift+N` opens the main window again; the tray provides the same action, Safe Mode, avatar toggle, and Quit.

Build the Unity renderer first with `npm run build:avatar --prefix apps/desktop`. In development the shell automatically discovers `apps/avatar-unity/Builds/NeuroAsistAvatar/NeuroAsistAvatar.exe`; production bundles include that directory as an `avatar` resource. `NEUROASIST_AVATAR_EXECUTABLE` remains an override for a custom renderer.

The shell gives Unity `NEUROASIST_BACKEND_URL` and `NEUROASIST_BACKEND_TOKEN`, enabling it to connect to the randomly selected, authenticated backend port. The tray **Show / hide avatar** action controls the active avatar presentation without restarting the renderer. In **Separate overlay** mode, hold `Ctrl+Alt` to temporarily make the click-through overlay interactive for drag/repositioning; `Ctrl+Alt+A` shows or hides it.

## Avatar placement

In **Settings → System → Avatar**, choose where the renderer appears:

- **Inside Iris** presents the Unity player as an Iris-owned transparent native surface in the lower-left column of the **Dialog** screen. It is hidden outside the chat, follows the chat-slot bounds when the window moves or resizes, and has no second visible application window or Alt+Tab entry. Its **Show in dialog** switch is independent from the external-overlay visibility setting.
- **Separate overlay** preserves the desktop companion behaviour: a borderless, click-through Unity window that can stay above other applications.

The choice is stored with the other non-secret runtime settings. On Windows, the in-app mode starts Unity hidden through its supported `-parentHWND ... delayed` path, waits until its graphics surface is ready, then manages it as a transparent popup owned by the Iris window. React supplies the exact DPI-aware chat-slot bounds, while Tauri reapplies them when Iris moves or resizes. Unity still runs as a supervised child process in this mode, so speech, lip sync, gestures and the authenticated WebSocket protocol remain unchanged.

## Safe Mode and recovery

Start the desktop binary with `--safe-mode` to skip Unity and backend model preloads. A crashed core is reported to the WebView and automatically receives one restart attempt; the `restart_core` Tauri command is available for a later in-UI recovery button.

## PyInstaller onedir spike

The initial packaging path is deliberately `--onedir`:

```powershell
.\apps\desktop\scripts\build-backend-onedir.ps1
```

For a packaged deployment, set `NEUROASIST_CORE_EXECUTABLE` to the generated `neuroasist-core.exe` before launching the shell. Shipping the executable as a Tauri external binary is deferred to the packaging milestone; this keeps the first desktop shell compatible with the local development runtime and avoids prematurely freezing a Windows installer layout.
