# NeuroAsist v0.3.1

[English](README.md) | Русский

NeuroAsist — локальный прототип голосового ассистента для будущего neuro-VTuber workflow. В текущей версии есть FastAPI backend, React/Vite web UI, доступ к DeepSeek-совместимому LLM, локальное STT через `faster-whisper` и локальный русский TTS через Silero.

## Что уже есть

- Текстовый чат через `POST /chat`.
- Push-to-talk голосовой чат через `POST /voice/chat`.
- Live-ответ голосом через WebSocket.
- Локальное STT через `faster-whisper`.
- Локальное TTS через Silero с WAV-выходом.
- История сообщений в SQLite.
- Runtime-события через WebSocket и `/events`.
- Browser SpeechSynthesis fallback, если backend TTS упал.

Пока вне v0.3.1: avatar/lipsync, always-on listening, пользователи, RAG, доступ к файлам, выполнение команд и desktop automation.

## Требования

- Примеры ниже написаны для Windows PowerShell, но Python/Node стек можно запускать и на других ОС.
- Python 3.12+.
- Node.js 24+.
- DeepSeek API key.
- FFmpeg и FFprobe в `PATH` для обработки голосовых upload/STT.
- Интернет для первого скачивания моделей.
- Опционально CUDA GPU для ускорения локальных моделей.

## Установка

Из корня репозитория:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

PyTorch ставится отдельно. По умолчанию используй CPU-вариант:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Для CUDA выбери команду на официальном PyTorch selector под свою видеокарту/драйвер/CUDA runtime. CUDA-сборку PyTorch не нужно добавлять в общий `requirements.txt`, потому что она зависит от машины.

Установи Silero:

```powershell
python -m pip install silero
```

Установи frontend-зависимости:

```powershell
npm install
npm install --prefix apps/web
```

Установи FFmpeg и проверь, что обе команды доступны в том же терминале, где будет запускаться backend:

```powershell
ffmpeg -version
ffprobe -version
```

Если Windows их не видит, добавь `bin` директорию FFmpeg в текущий терминал:

```powershell
$env:Path = "C:\Path\To\ffmpeg\bin;$env:Path"
```

## Настройка

Скопируй `.env.example` в `.env`:

```powershell
Copy-Item .env.example .env
```

Минимально нужно заполнить:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
```

Текущая голосовая конфигурация по умолчанию:

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

Поведение `VOICE_SILERO_DEVICE`:

- `cpu`: всегда использует CPU.
- `cuda`: требует CUDA и понятно падает, если CUDA недоступна.
- `auto`: пробует CUDA и переключается на CPU.

Первый запуск backend с Silero скачивает модель через PyTorch Hub. Для полностью офлайн-запуска нужно один раз запустить backend с интернетом и дождаться preload. Кэш Torch обычно находится в `%USERPROFILE%\.cache\torch\hub` на Windows.

Перед коммерческим использованием проверь лицензию выбранной Silero-модели.

## Запуск

Backend:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```powershell
npm --prefix apps/web run dev
```

Открыть UI:

```text
http://127.0.0.1:5173
```

API docs:

```text
http://127.0.0.1:8000/docs
```

Если порт `8000` занят:

```powershell
netstat -ano | Select-String ":8000"
Stop-Process -Id <PID> -Force
```

## Голосовой pipeline

Обычный voice chat:

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

Если backend TTS падает, текстовый ответ всё равно остаётся доступным, а браузер может использовать SpeechSynthesis fallback.

## Полезные команды

Backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Frontend tests:

```powershell
npm test --prefix apps/web
```

Frontend build:

```powershell
npm run build
```

Benchmark Silero:

```powershell
python scripts/benchmark_tts.py --provider silero --device cpu --runs 5
python scripts/benchmark_tts.py --provider silero --device cuda --runs 5
```

Benchmark сохраняет JSON в `data/tts_benchmark.json` и печатает P50/P95 synthesis time и RTF.

## API-примеры

Health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Текстовый чат:

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

Голосовой чат:

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

Форма voice response:

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

Текст возвращается сразу. TTS продолжает работать в фоне и публикует `voice.tts_ready`, когда WAV готов.

## Частые проблемы

- `Silero model is not loaded`: обнови репозиторий до свежего состояния; некоторые Silero-модели делают `.to(device)` in-place.
- `torch is not installed`: установи PyTorch отдельно, затем `silero`.
- `CUDA is not available`: поставь `VOICE_SILERO_DEVICE=cpu` или установи CUDA-совместимую сборку PyTorch.
- Первый запуск долгий: Silero скачивает и прогревает модель.
- Backend не читает audio: проверь `ffmpeg -version` и `ffprobe -version` в backend-терминале.
- После падения backend TTS нет звука: проверь browser fallback и разрешения браузера на audio playback.

## Структура проекта

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
