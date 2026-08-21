# Эксплуатация и сборка Iris

Команды ниже выполняются из корня репозитория в PowerShell. Поддерживаемая
development-платформа — Windows 10/11.

## Development startup

Полная подготовка окружения описана в [README](../README.ru.md). Обычный запуск:

```powershell
npm --prefix apps/desktop run dev
```

Tauri запускает Vite и `python -m apps.backend.desktop_entry`, выбирает
свободный loopback port, создаёт session token и останавливает дочерние процессы
при выходе. Для восстановления окна используйте tray. Safe Mode запускает core
без Unity и preload локальных voice-моделей.

Раздельный browser/backend режим:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
npm --prefix apps/web run dev
```

## Данные

Desktop shell задаёт `%LOCALAPPDATA%\NeuroAsist` как writable data root:

```text
%LOCALAPPDATA%\NeuroAsist\
├── data\neuroasist.sqlite3   timeline, memory, jobs and character state
├── data\audio\              short-lived generated TTS files
├── settings.json             non-secret runtime settings
├── backups\                  portable ZIP snapshots
├── logs\app.log              desktop core log
├── models\                   managed/local model data
├── stt-terms.json
└── tts-pronunciations.json
```

`NEUROASIST_APP_DATA_DIR` changes the root. In browser development the relative
`SQLITE_PATH` and `VOICE_AUDIO_DIR` defaults resolve against the repository.

API keys are supplied by `.env` in development or Windows Credential Manager
in desktop mode. They are not written to `settings.json` or backups.

## Logs and diagnostics

- **Settings → System → Events** shows recent runtime events.
- `GET /status` reports application version, database and LLM configuration.
- `GET /readiness` separates text, STT, TTS and live readiness.
- `GET /diagnostics` exposes storage/runtime diagnostics.
- `GET /debug/llm/usage` contains content-free usage, cache, reasoning, retry and latency records.
- Desktop logs are written to `%LOCALAPPDATA%\NeuroAsist\logs\app.log`.

When reporting a problem, include the application version, relevant event IDs,
model status and a short log excerpt. Do not attach `.env`, Credential Manager
entries, message text or the whole SQLite database unless intentionally sharing
private conversation data.

## Backups

**Settings → System → Backups** creates a ZIP containing a consistent SQLite
snapshot and `settings.json`; API keys are excluded. The service prunes files
older than `BACKUP_RETENTION_DAYS`.

Iris 1.0 can create, list and delete backups but does not yet expose an in-app
restore action. Treat a backup as verified only after inspecting the ZIP and
opening the copied SQLite database with `PRAGMA integrity_check`. A supported,
tested restore flow is a public-release gate in [release-checklist.md](release-checklist.md).

Never replace a live database while the backend is running.

## Verification matrix

### Fast checks

```powershell
.\.venv\Scripts\python.exe scripts/check_docs.py
.\.venv\Scripts\python.exe -m compileall -q apps/backend
.\.venv\Scripts\python.exe -m pip check
npm --prefix apps/web run build
npm --prefix apps/web audit --omit=dev --audit-level=high
npm --prefix apps/desktop audit --omit=dev --audit-level=high
npm --prefix apps/desktop run check
```

### Regression suites

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/web test
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

### Desktop lifecycle smoke

```powershell
.\scripts\smoke_desktop_core.ps1
```

It verifies authenticated startup, rejection without the token and graceful
shutdown using temporary data and mock voice providers.

### Startup benchmark

```powershell
.\scripts\benchmark-startup.ps1 -Scenario both
```

The script measures clean and cached text/live readiness. Save the JSON output
for release-to-release comparison.

### Synthetic conversation soak

```powershell
.\.venv\Scripts\python.exe scripts\live_conversation_soak.py --duration 300 --cycles 120
```

This exercises conversation state and cancellation without a microphone. It
does not replace a real-audio soak with reconnect, barge-in and Unity playback.

## Coding Agent runtime

Build the no-network sandbox image whenever its Dockerfile changes:

```powershell
docker build -t neuroasist-coding -f apps/backend/docker/coding.Dockerfile apps/backend/docker
```

Confirm Docker Desktop is running and open `/coding/status` or the Coding Agent
screen. A missing daemon/image must make the agent unavailable; it must never
execute on the host. See [coding-agent.md](coding-agent.md).

## Unity avatar build

```powershell
$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\2022.3.62f3\Editor\Unity.exe'
npm --prefix apps/desktop run build:avatar
```

Close Unity Editor and any running avatar process first. Output:
`apps\avatar-unity\Builds\NeuroAsistAvatar\NeuroAsistAvatar.exe`.

## Windows release build

Prerequisites: clean worktree, synchronized `VERSION`, green verification
matrix, Unity avatar build, enough disk space for the Python ML runtime, and
PyInstaller/build dependencies available through the script.

```powershell
.\scripts\build-desktop-release.ps1
```

The script builds the PyInstaller `--onedir` core, temporarily adds it to Tauri
resources, builds NSIS and restores `tauri.conf.json` in `finally`. Installer
output:

```text
apps\desktop\src-tauri\target\release\bundle\nsis\
```

For repeated builds after dependencies are already installed:

```powershell
.\scripts\build-desktop-release.ps1 -SkipDependencyInstall
```

Smoke a standalone packaged core when an executable has been produced:

```powershell
.\scripts\smoke_packaged_runtime.ps1 -Executable <path-to-neuroasist-core.exe>
```

Do not publish merely because the build succeeds. Complete every required item
in [Release checklist 1.0](release-checklist.md), including clean-VM install,
upgrade, uninstall, backup recovery, real voice soak and license review.

## Failure handling

- If text is unavailable, check `/status`, API-key availability and LLM events.
- If voice is unavailable, check `/readiness`, Models, microphone permission and FFmpeg.
- If a worker crashes, look for `backend.worker_failed`; the supervisor retries with bounded backoff.
- If Unity fails, use Safe Mode, then inspect avatar status and the Unity build log.
- If a settings write fails, the previous runtime/file state remains authoritative; fix filesystem access and retry.
- If SQLite reports an error, stop Iris, preserve the database and latest backup, and investigate a copy.
