# NeuroAsist

NeuroAsist is an early local-first skeleton for a voice-capable neuro-VTuber
assistant.

Current scope:

- FastAPI backend
- `POST /chat` endpoint
- OpenAI-compatible DeepSeek provider
- `CharacterAgent`
- SQLite message history
- `.env` configuration
- React + TypeScript Web UI
- backend runtime events over WebSocket
- v0.3 push-to-talk voice chat with fast STT and optional TTS provider abstractions
- `faster-whisper` STT and background `edge-tts` TTS provider

Out of scope for v0.3: avatar, lipsync, always-on listening, streaming voice,
file access, command execution,
dev-agent, screen context, long-term memory, embeddings, RAG, users, and auth.

## Requirements

- Python 3.12+
- Node.js 24+
- DeepSeek API key
- FFmpeg and FFprobe on PATH for real audio transcription, TTS validation, and
  multi-chunk Edge TTS concatenation

Install backend dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
cd apps\web
npm install
```

## Quick Start

Use two PowerShell windows.

Backend window:

```powershell
cd B:\NeuroAsist
.\.venv\Scripts\Activate.ps1
$env:Path = "C:\Users\OLEG\Tools\ffmpeg\bin;$env:Path"
ffmpeg -version
ffprobe -version
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend window:

```powershell
cd B:\NeuroAsist\apps\web
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

If backend startup fails with `WinError 10013`, port `8000` is already in use.
Find and stop the listener:

```powershell
netstat -ano | Select-String ":8000"
Stop-Process -Id <PID> -Force
```

If `ffmpeg` or `ffprobe` is not found after installation, restart PowerShell or
prepend the FFmpeg bin directory in the same terminal before starting backend:

```powershell
$env:Path = "C:\Users\OLEG\Tools\ffmpeg\bin;$env:Path"
```

## Configuration

Copy `.env.example` to `.env` and fill in your API key:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
SQLITE_PATH=data/neuroasist.sqlite3
CHAT_HISTORY_LIMIT=20
LOG_LEVEL=WARNING
LOG_TO_FILE=true
LOG_FILE_PATH=logs/app.log
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
CORS_ORIGIN_REGEX=^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$
VOICE_STT_PROVIDER=faster_whisper
VOICE_STT_MODEL=small
VOICE_STT_DEVICE=cpu
VOICE_STT_COMPUTE_TYPE=int8
VOICE_DEFAULT_LANGUAGE=ru
VOICE_PRELOAD_STT_MODEL=true
VOICE_TTS_ENABLED=true
VOICE_TTS_PROVIDER=edge_tts
VOICE_TTS_VOICE_RU=ru-RU-SvetlanaNeural
VOICE_TTS_VOICE_EN=en-US-AriaNeural
VOICE_TTS_BACKGROUND_TIMEOUT_SECONDS=20
VOICE_TTS_MAX_CHARS=1200
VOICE_AUDIO_DIR=data/audio
VOICE_MAX_UPLOAD_MB=25
VOICE_MAX_RECORD_SECONDS=60
VOICE_STT_TIMEOUT_SECONDS=45
VOICE_LLM_TIMEOUT_SECONDS=45
VOICE_TTS_TIMEOUT_SECONDS=45
```

`.env` is local-only and must not be committed. `.env.example` documents the
settings required to run the project.

## Run Backend

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open the API docs:

```text
http://127.0.0.1:8000/docs
```

Backend URLs:

```text
API:       http://127.0.0.1:8000
WebSocket: ws://127.0.0.1:8000/ws/events
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Chat request:

```powershell
$body = @{
  session_id = "default"
  message = "Привет, кто ты?"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/chat `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

Expected response shape:

```json
{
  "reply": "string",
  "emotion": "neutral",
  "intent": "casual_chat"
}
```

Voice chat request:

```powershell
$form = @{
  session_id = "default"
  language = "ru"
  audio = Get-Item .\sample.webm
}

Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/voice/chat `
  -Method Post `
  -Form $form
```

Expected voice response shape:

```json
{
  "transcript": "string",
  "reply": "string",
  "emotion": "neutral",
  "intent": "casual_chat",
  "voice_request_id": "<id>",
  "reply_audio_url": null,
  "tts_status": "queued",
  "stt": {"provider": "faster_whisper", "model": "small", "language": "ru", "duration_ms": 1200},
  "tts": {"provider": "edge_tts", "voice": "ru-RU-SvetlanaNeural", "duration_ms": 0}
}
```

The text response is returned before TTS completes. When audio is ready, the
backend publishes a `voice.tts_ready` WebSocket event with `voice_request_id`
and `audio_url`; the web UI attaches that audio to the matching assistant
message.

Edge TTS notes:

- backend prefers Edge TTS audio over browser speech;
- Russian Edge voices can fall back to Edge multilingual voices if a provider
  returns no audio;
- short comma-heavy phrases stay in one TTS chunk for more natural pacing;
- Edge TTS is currently sent with `rate="+20%"`;
- FFmpeg/FFprobe must be visible to the backend process for multi-chunk
  concatenation and duration validation.

## Run Frontend

From `apps/web`:

```powershell
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Frontend environment:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_WS_EVENTS_URL=ws://127.0.0.1:8000/ws/events
```

Production build:

```powershell
npm run build
```

## v0.3 Web UI

The local web panel includes:

- Chat: sends messages to `POST /chat` and shows `emotion` / `intent`.
- Voice: toggle recording sends browser audio to `POST /voice/chat`.
- Events: loads `GET /events` and receives live `WS /ws/events` events.
- Settings: shows safe provider settings and updates runtime model/personality
  plus voice language/TTS voice.
- TTS: background Edge TTS jobs report `queued` / `ready` / `failed`; ready
  audio is attached to the assistant message and played from `/voice/audio`.

The browser never receives or stores the DeepSeek API key.

## Project Layout

```text
apps/
  backend/
    main.py
    app/
      agents/character/
      api/routes/
      core/
      events/
      llm/providers/
      runtime/
      schemas/
      storage/
  web/
    src/
```

The backend keeps LLM access behind a provider interface so another
OpenAI-compatible model can replace DeepSeek without changing the route or
agent logic.
