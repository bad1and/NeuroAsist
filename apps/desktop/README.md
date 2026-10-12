# Iris Desktop Shell

The desktop shell is a Tauri 2 application around the existing React UI and FastAPI core. It starts the core on a randomly selected loopback port, injects an ephemeral token into the WebView before React starts, and terminates its managed child processes on exit.

## Development

Run all commands from the repository root. First prepare Python, Node.js,
Rust, Microsoft C++ Build Tools and WebView2 using
[the dependency guide](../../Docs/dependencies.md). The CPU profile is the
default; [hardware requirements](../../Docs/system-requirements.md) distinguish
estimated minimums from the reference computer. Install the root npm package
as well (`npm ci`).

```powershell
npm ci --prefix apps/desktop
npm ci --prefix apps/web
```

Start the companion with one command:

```powershell
npm --prefix apps/desktop run dev
```

The shell starts Vite and `python -m apps.backend.desktop_entry` itself, so no separate backend process or browser tab is required. If Windows asks `Terminate batch job (Y/N)?` after `Ctrl+C`, answer `Y`; the shell then stops the managed backend cleanly.

The Unity Editor path is needed only when rebuilding the avatar renderer:

```powershell
$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\2022.3.62f3\Editor\Unity.exe'
npm --prefix apps/desktop run build:avatar
```

Use Unity 2022.3.62f3 with Windows Build Support (Mono); adjust the installation path if necessary. A clean clone has no built avatar, so the editor is needed for its first build as well as rebuilds. Text and voice work without the avatar. The environment variable applies only to the current PowerShell session and must be set again in a new terminal.

The dev shell uses the repository `.venv\Scripts\python.exe` when present. `CommandOrControl+Shift+N` opens the main window again; the tray provides the same action, Safe Mode, avatar toggle, and Quit (Выйти in the Russian interface).

Closing the main window starts graceful shutdown and exits the application;
minimizing it keeps the app running. The tray Quit action also stops the
managed core and avatar.

Build the Unity renderer first with `npm run build:avatar --prefix apps/desktop`. In development the shell automatically discovers `apps/avatar-unity/Builds/NeuroAsistAvatar/NeuroAsistAvatar.exe`; production bundles include that directory as an `avatar` resource. `NEUROASIST_AVATAR_EXECUTABLE` remains an override for a custom renderer.

The shell gives Unity `NEUROASIST_BACKEND_URL` and `NEUROASIST_BACKEND_TOKEN`, enabling it to connect to the randomly selected, authenticated backend port. The tray **Show / hide avatar** action controls the active avatar presentation without restarting the renderer. In **Separate overlay** mode, hold `Ctrl+Alt` to temporarily make the click-through overlay interactive for drag/repositioning; `Ctrl+Alt+A` shows or hides it.

## Avatar placement

In **Settings → System → Avatar**, choose where the renderer appears:

- **Inside Iris** presents the Unity player as an Iris-owned, transparent, borderless native surface in the lower-left column of the **Dialog** screen. It is hidden outside the chat, scales with the available chat area, follows DPI changes, and has no second visible application window or Alt+Tab entry. Its **Show in dialog** switch is independent from the external-overlay visibility setting.
- **Separate overlay** preserves the desktop companion behaviour: a borderless, click-through Unity window that can stay above other applications.

The choice is stored with the other non-secret runtime settings. On Windows, in-app mode starts Unity as a tiny hidden player, then converts its ready render window into a transparent popup owned by Iris. React supplies the exact DPI-aware chat-slot bounds with frame-coalesced updates; the owned popup follows normal window movement without fighting the Windows drag loop. The embedded profile caps Unity at 60 FPS, disables VSync, HDR, shadows, reflection probes and anisotropic filtering, and uses lightweight 2× MSAA to clean avatar edges without competing with the WebView. Its neutral Iris-matched colour key replaces the former saturated blue matte, greatly reducing coloured fringe around anti-aliased hair and clothing; the separate overlay keeps its own higher-quality presentation unchanged. Unity still runs as a supervised child process in both modes, so speech, lip sync, gestures and the authenticated WebSocket v2 protocol remain unchanged.

## Safe Mode and recovery

Start the desktop binary with `--safe-mode` to skip Unity and backend model preloads. A crashed core is reported to the WebView and automatically receives one restart attempt; the `restart_core` Tauri command is available for a later in-UI recovery button.

## Release build

The supported release path builds a PyInstaller `--onedir` core and includes it
as a Tauri resource:

```powershell
.\scripts\build-desktop-release.ps1
```

The installer is written under
`apps\desktop\src-tauri\target\release\bundle\nsis`. Use
`apps\desktop\scripts\build-backend-onedir.ps1` only for an isolated core
packaging check. Release prerequisites and acceptance gates are documented in
[`Docs/operations.md`](../../Docs/operations.md) and
[`Docs/release-checklist.md`](../../Docs/release-checklist.md).

## Приложение перед установщиком

Из корня репозитория выполните `scripts/build-preinstaller-app.ps1`. Команда
собирает Unity, CPU onedir и Tauri с `--no-bundle`; путь Unity Editor задаётся
через `NEUROASIST_UNITY_EDITOR`. Для уже проверенного аватара доступен
`-SkipAvatarBuild`. Python-окружение разработчика не изменяется.

Все изменяемые данные находятся в `%LOCALAPPDATA%\NeuroAsist`. Веса загружаются
через настройки; восстановление ZIP и удаление моделей выполняются при
остановленном ядре. При ошибке запуска импорт и восстановление доступны
на стартовом экране. Coding-проекты выбираются системным диалогом; задания
хранятся в пользовательском профиле.

[Приёмка каталога приложения](../../Docs/preinstaller-readiness.md) предшествует
сборке и испытанию установщика. Лицензии и реальные аппаратные сценарии
подтверждаются отдельно от автоматики.

Production CSP разрешает статический CSS Paper Shaders по SHA-256 и inline
атрибуты стилей для React/Anime.js. Скрипты, соединения и медиаресурсы ограничены
явными источниками. После обновления Paper Shaders проверяйте CSP в реальном
WebView: изменение CSS требует обновления разрешённого хеша.
