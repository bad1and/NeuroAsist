# NeuroAsist v0.3.1

🇺🇸 [English](README.md) | 🇷🇺 [Русский](README.ru.md)

NeuroAsist is a local-first voice assistant prototype for a future neuro-VTuber workflow. The current version includes a FastAPI backend, React/Vite web UI, DeepSeek-compatible LLM access, local STT through `faster-whisper`, and local Russian TTS through Silero.

## Current Scope

- Text chat via `POST /chat`.
- Push-to-talk voice chat via `POST /voice/chat`.
- Live voice response over WebSocket.
- Local STT with `faster-whisper`.
- Local Silero TTS with WAV output.
- SQLite chat history.
- Runtime events over WebSocket and `/events`.
- Browser SpeechSynthesis fallback when backend TTS fails.

Out of scope for v0.3.1: avatar/lipsync, always-on listening, user accounts, RAG, file access, command execution, and desktop automation.

## Requirements

- Windows PowerShell examples assume Windows, but the Python/Node stack is cross-platform.
- Python 3.12+.
- Node.js 24+.
- DeepSeek API key.
- FFmpeg and FFprobe on `PATH` for audio upload/STT validation.
- Internet access for the first model download.
- Optional CUDA-capable GPU for faster local models.

## Installation

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install PyTorch separately. CPU is the default and safest install:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

For CUDA, use the official PyTorch selector and install the wheel that matches your driver/CUDA runtime. Do not add a CUDA-specific PyTorch wheel to `requirements.txt`, because CPU and CUDA installs differ per machine.

Install Silero:

```powershell
python -m pip install silero
```

Install the frontend dependencies:

```powershell
npm install
npm install --prefix apps/web
```

Install FFmpeg, then make sure both commands work in the same terminal where you run the backend:

```powershell
ffmpeg -version
ffprobe -version
```

If Windows cannot find them, add your FFmpeg `bin` directory for the current terminal:

```powershell
$env:Path = "C:\Path\To\ffmpeg\bin;$env:Path"
```

## Configuration

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Set at least:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
```

Default voice configuration:

```env
VOICE_STT_PROVIDER=faster_whisper
VOICE_STT_MODEL=small
VOICE_STT_DEVICE=auto
VOICE_STT_COMPUTE_TYPE=int8

VOICE_TTS_ENABLED=true
VOICE_TTS_PROVIDER=silero
VOICE_PRELOAD_TTS_MODEL=true
VOICE_SILERO_MODEL=v5_5_ru
VOICE_SILERO_SPEAKER_RU=xenia
VOICE_SILERO_SAMPLE_RATE=24000
VOICE_SILERO_DEVICE=cpu
VOICE_SILERO_CPU_THREADS=4
VOICE_SILERO_WARMUP=true
VOICE_SILERO_TIMEOUT_SECONDS=10
```

Silero device behavior:

- `cpu`: always uses CPU.
- `cuda`: requires CUDA and fails clearly if CUDA is unavailable.
- `auto`: tries CUDA and falls back to CPU.

The first backend start with Silero downloads the model through PyTorch Hub. For offline use, start once with internet access and let preload finish. The model is cached by Torch, usually under `%USERPROFILE%\.cache\torch\hub` on Windows.

Check the selected Silero model license before commercial use.

## Run

Backend:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```powershell
npm --prefix apps/web run dev
```

Open:

```text
http://127.0.0.1:5173
```

API docs:

```text
http://127.0.0.1:8000/docs
```

If port `8000` is busy:

```powershell
netstat -ano | Select-String ":8000"
Stop-Process -Id <PID> -Force
```

## Voice Pipeline

Batch voice chat:

```text
Browser MediaRecorder
  -> POST /voice/chat
  -> faster-whisper STT
  -> DeepSeekProvider + CharacterAgent
  -> SileroTTSProvider
  -> WAV PCM 16-bit / 24000 Hz / mono
  -> GET /voice/audio/{audio_id}
```

Live voice:

```text
LLM streaming
  -> TextChunker
  -> SileroTTSProvider
  -> WAV segment
  -> WebSocket
  -> TTSStreamPlayer.decodeAudioData()
```

Backend TTS failures are recoverable: the text reply remains available and the browser can use SpeechSynthesis fallback.

## Useful Commands

Run backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run frontend tests:

```powershell
npm test --prefix apps/web
```

Build frontend:

```powershell
npm run build
```

Benchmark Silero:

```powershell
python scripts/benchmark_tts.py --provider silero --device cpu --runs 5
python scripts/benchmark_tts.py --provider silero --device cuda --runs 5
```

The benchmark writes JSON to `data/tts_benchmark.json` and prints P50/P95 synthesis time and RTF.

## API Examples

Health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Text chat:

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

Voice chat:

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

Voice response shape:

```json
{
  "voice_request_id": "<id>",
  "transcript": "string",
  "reply": "string",
  "emotion": "neutral",
  "intent": "casual_chat",
  "reply_audio_url": null,
  "tts_status": "queued",
  "stt": {"provider": "faster_whisper", "model": "small", "language": "ru", "duration_ms": 1200},
  "tts": {"provider": "silero", "voice": "xenia", "duration_ms": 0}
}
```

The text response returns immediately. TTS continues in the background and publishes `voice.tts_ready` when the WAV file is ready.

## Troubleshooting

- `Silero model is not loaded`: update to the latest repository state; Silero models may move to device in-place.
- `torch is not installed`: install PyTorch separately, then install `silero`.
- `CUDA is not available`: set `VOICE_SILERO_DEVICE=cpu` or install a CUDA-compatible PyTorch build.
- First startup is slow: the Silero model is downloading and warming up.
- Backend cannot read audio: check `ffmpeg -version` and `ffprobe -version` in the backend terminal.
- Browser has no audio after backend TTS failure: check the UI fallback and browser audio permissions.

## Project Layout

```text
apps/
  backend/
    main.py
    app/
      agents/
      api/
      core/
      events/
      llm/
      runtime/
      schemas/
      storage/
      voice/
  web/
    src/
scripts/
tests/
Docs/
```
