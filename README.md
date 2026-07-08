# NeuroAsist

NeuroAsist is an early local-first skeleton for a text-first neuro-VTuber
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

Out of scope for v0.2: voice, avatar, STT/TTS, file access, command execution,
dev-agent, screen context, long-term memory, embeddings, RAG, users, and auth.

## Requirements

- Python 3.12+
- Node.js 24+
- DeepSeek API key

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
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend window:

```powershell
cd B:\NeuroAsist\apps\web
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

## v0.2 Web UI

The local web panel includes:

- Chat: sends messages to `POST /chat` and shows `emotion` / `intent`.
- Events: loads `GET /events` and receives live `WS /ws/events` events.
- Settings: shows safe provider settings and updates runtime model/personality.

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
