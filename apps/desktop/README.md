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

Official Unity builds use authorized inputs in the private avatar repository.
The [split build guide](../../Docs/avatar-distribution.md) describes the verified
Player archive and application assembly. In development the shell automatically
discovers `apps/avatar-unity/Builds/NeuroAsistAvatar/NeuroAsistAvatar.exe`;
the release build script maps the verified Player to the `avatar` resource.
`NEUROASIST_AVATAR_EXECUTABLE` remains an override for a custom renderer.

The shell gives Unity `NEUROASIST_BACKEND_URL` and `NEUROASIST_BACKEND_TOKEN`, enabling it to connect to the randomly selected, authenticated backend port. The tray **Show / hide avatar** action controls the active presentation; `Ctrl+Alt+A` also shows or hides it. Desktop movement and resizing use the avatar's hover controls and their shared lock.

## Avatar placement

In **Settings → Conversation → Avatar**, choose where the renderer appears:

- **Inside Iris** presents the Unity player as an Iris-owned, transparent, borderless native surface in the lower-left column of the **Dialog** screen. It is hidden outside the chat, scales with the available chat area, follows DPI changes, and has no second visible application window or Alt+Tab entry. Its **Show in dialog** switch is independent from the external-overlay visibility setting.
- **On the desktop** offers **Waist up**, anchored to the bottom of the monitor work area above the taskbar, and **Full body**, a standing figure that can move freely between monitors. Each mode remembers its own monitor, size and position. The monitor selector moves the active mode to a chosen display; unavailable displays fall back to the primary monitor.

Image quality is saved independently for **Inside Iris** and **On the desktop** and applies immediately. Low uses 2x MSAA at 30 FPS; Medium uses 4x MSAA at 60 FPS inside Iris or 30 FPS on the desktop; High uses 8x MSAA at 60 FPS. Shadow-map resolution follows the preset, while soft shadows remain enabled to preserve the character's original skin and clothing tones. Defaults are High inside Iris and Medium on the desktop. The GPU can fall back to its supported MSAA sample count.

The choice is stored with the other non-secret runtime settings. Windows hosts Unity as a supervised transparent native popup, using D3D11 BitBlt and DWM coverage alpha. In-app ownership belongs to the main window; desktop ownership belongs to an independent transparent Tauri window, so minimizing Iris does not hide the desktop figure. Tauri alone controls desktop bounds and monitor/DPI conversion; the managed Unity host does not write its own bounds or scale its model root.

Hover over the desktop figure to show microphone, Iris audio, text, tools, open-app and lock buttons. Unlocking reveals an upper-corner resize handle. The common lock prevents both moving and resizing while keeping the buttons usable; the locked figure passes clicks through to the desktop. Text and document attachments use the main window's existing conversation and audio owner. Attachments currently support TXT, MD and text PDF up to 10 MB.

Desktop subtitles are independent from hover, appear during Iris speech, and disappear two seconds after playback ends. Idle snapshots and historical messages do not bring the last line back. They use at most two rendered lines and can be placed above, below, left or right. The host fits them inside the work area when the preferred side is unavailable. Audio mute keeps the speech clock and subtitles running and also mutes Unity's subsequent replies. New preference fields extend `/avatar/overlay`; legacy preferences migrate to the waist-up layout on first desktop-host initialization.

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
