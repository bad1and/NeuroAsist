# NeuroAsist

NeuroAsist is an early v0.1 skeleton for a text-first neuro-VTuber assistant.

Current scope:

- FastAPI backend
- `POST /chat` endpoint
- OpenAI-compatible DeepSeek provider
- `CharacterAgent`
- SQLite message history
- `.env` configuration

Out of scope for v0.1: voice, avatar, STT/TTS, file access, command execution,
dev-agent, screen context, long-term memory, embeddings, and RAG.

## Requirements

- Python 3.12+
- DeepSeek API key

Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and fill in your API key:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
SQLITE_PATH=data/neuroasist.sqlite3
CHAT_HISTORY_LIMIT=20
```

`.env` is local-only and must not be committed. `.env.example` documents the
settings required to run the project.

## Run

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open the API docs:

```text
http://127.0.0.1:8000/docs
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

## Project Layout

```text
apps/
  backend/
    main.py
    app/
      agents/character/
      api/routes/
      core/
      llm/providers/
      schemas/
      storage/
  web/
```

The backend keeps LLM access behind a provider interface so another
OpenAI-compatible model can replace DeepSeek without changing the route or
agent logic.
