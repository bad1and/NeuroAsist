<div align="center">

# NeuroAsist

### Local-first voice AI character and future neuro‑VTuber platform

[![Version](https://img.shields.io/badge/version-0.3.1-7c3aed?style=flat-square)](https://github.com/bad1and/NeuroAsist/tree/v0.3.1)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-24%2B-339933?style=flat-square&logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square&logo=react&logoColor=111827)](https://react.dev/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)](LICENSE)

**English** · [Русская версия](README.ru.md) · [Project Blueprint](Docs/neuro_vtuber_assistant_blueprint_v1.1.md)

</div>

> [!IMPORTANT]
> **NeuroAsist v0.3.1 is an experimental local prototype.**  
> Text chat, push-to-talk, local speech recognition, local speech synthesis, and live voice playback are already implemented. Avatar rendering, lip sync, desktop access, and the development agent are planned for future versions.

## About the project

NeuroAsist is a local control panel and backend for an AI character that can hear the user, understand a request, generate a response, and speak it aloud.

The current release focuses on a stable voice interaction loop:

```mermaid
flowchart LR
    A[Microphone or text] --> B[faster-whisper STT]
    B --> C[Character Agent]
    C --> D[DeepSeek-compatible LLM]
    D --> E[Silero TTS]
    E --> F[Voice playback]
```

The long-term goal is to turn this foundation into a modular neuro‑VTuber platform with an animated avatar, emotions, memory, controlled tools, and a sandboxed development agent.

## Current capabilities

| Capability | Status | Implementation |
|---|:---:|---|
| Text conversation | ✅ | FastAPI chat endpoint |
| Push-to-talk voice chat | ✅ | Browser `MediaRecorder` |
| Live voice response | ✅ | WebSocket audio segments |
| Local speech-to-text | ✅ | `faster-whisper` |
| Local Russian text-to-speech | ✅ | Silero `v5_5_ru` |
| Conversation history | ✅ | SQLite |
| Runtime events | ✅ | REST and WebSocket |
| Model and voice settings | ✅ | Local React control panel |
| Browser speech fallback | ✅ | Used when backend TTS fails |
| Avatar and lip sync | 🧭 | Planned |
| Development agent and sandbox | 🧭 | Planned |
| Screen and desktop context | 🧭 | Planned |

## Key ideas

- **Local-first voice processing** — STT and TTS run on the user's machine.
- **Fast text response** — the text reply can be returned before background TTS finishes.
- **Fail-soft audio** — a TTS failure does not destroy a successful text response.
- **Observable runtime** — backend, chat, STT, TTS, and WebSocket events are visible in the UI.
- **Modular structure** — LLM, STT, TTS, storage, events, and agents are separated by responsibility.
- **Restricted current scope** — v0.3.1 cannot execute commands, browse files, or control the desktop.

## Interface

The React control panel contains three main sections:

- **Chat** — text messages, microphone recording, transcription, AI replies, and audio playback.
- **Events** — live backend, LLM, STT, TTS, and connection events.
- **Settings** — model, language, and available TTS voice selection.

The header displays backend status, WebSocket connection state, API-key availability, and the currently selected model.

## Technology stack

### Backend

- Python 3.12+
- FastAPI
- Pydantic Settings
- SQLite
- WebSocket
- `faster-whisper`
- Silero TTS
- DeepSeek-compatible LLM API

### Frontend

- React 19
- TypeScript
- Vite
- Vitest
- Browser MediaRecorder
- Web Audio API

## Quick start

### Requirements

- Windows 10/11 is the primary development platform;
- Python **3.12+**;
- Node.js **24+**;
- FFmpeg and FFprobe available through `PATH`;
- a DeepSeek API key;
- internet access for the first Whisper and Silero model download;
- optional CUDA-capable GPU.

### 1. Clone the release branch

```powershell
git clone --branch v0.3.1 --single-branch https://github.com/bad1and/NeuroAsist.git
cd NeuroAsist
```

### 2. Create a Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install PyTorch separately. The CPU build is the most portable option:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install silero
```

For CUDA, install the PyTorch build matching the installed GPU driver and CUDA runtime.

### 3. Install frontend dependencies

```powershell
npm install
npm install --prefix apps/web
```

### 4. Configure the environment

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
```

### 5. Verify FFmpeg

```powershell
ffmpeg -version
ffprobe -version
```

If Windows cannot find FFmpeg in the current terminal:

```powershell
$env:Path = "C:\Path\To\ffmpeg\bin;$env:Path"
```

### 6. Start the backend

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 7. Start the frontend

Open a second terminal:

```powershell
npm --prefix apps/web run dev
```

Open:

- Web UI: `http://127.0.0.1:5173`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## Architecture

```mermaid
flowchart TB
    UI[React and TypeScript Web UI]

    subgraph Backend[FastAPI backend]
        API[REST API]
        WS[Events and voice WebSockets]
        Agent[Character Agent]
        Runtime[Runtime settings]
        Events[Event Bus]
        Voice[Voice Service]
        History[SQLite history]
    end

    STT[faster-whisper]
    LLM[DeepSeek-compatible API]
    TTS[Silero TTS]
    Audio[WAV audio storage]

    UI <-->|REST| API
    UI <-->|WebSocket| WS
    API --> Agent
    API --> Voice
    API --> Runtime
    Agent --> History
    Agent --> LLM
    Agent --> Events
    Voice --> STT
    Voice --> TTS
    TTS --> Audio
    Events --> WS
    TTS --> WS
```

The backend is a modular monolith: API routes, agents, voice providers, runtime settings, events, and storage live in one Python application, while the web interface is a separate Vite application.

This keeps the prototype easy to run and debug without introducing unnecessary infrastructure.

## Voice pipeline

### Standard push-to-talk

```text
Browser MediaRecorder
  → POST /voice/chat
  → faster-whisper
  → Character Agent
  → DeepSeek-compatible LLM
  → immediate text response
  → background Silero synthesis
  → ready WAV audio
```

The text response is returned before TTS finishes. The UI then receives the generated audio when it becomes ready.

### Live voice response

```text
LLM text stream
  → safe text chunks
  → Silero WAV segments
  → voice WebSocket
  → browser playback queue
```

The live mode uses configurable chunk sizes, queue limits, TTS concurrency, and playback prebuffering.

## Project structure

```text
NeuroAsist/
├── apps/
│   ├── backend/
│   │   ├── main.py
│   │   └── app/
│   │       ├── agents/
│   │       ├── api/
│   │       ├── core/
│   │       ├── events/
│   │       ├── llm/
│   │       ├── runtime/
│   │       ├── schemas/
│   │       ├── storage/
│   │       └── voice/
│   └── web/
│       └── src/
├── Docs/
│   └── neuro_vtuber_assistant_blueprint_v1.1.md
├── scripts/
├── tests/
├── main.py
├── requirements.txt
└── package.json
```

## Development commands

Run backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run frontend tests:

```powershell
npm test --prefix apps/web
```

Build the frontend:

```powershell
npm run build
```

Benchmark Silero:

```powershell
python scripts/benchmark_tts.py --provider silero --device cpu --runs 5
python scripts/benchmark_tts.py --provider silero --device cuda --runs 5
```

The benchmark writes results to `data/tts_benchmark.json` and reports P50/P95 synthesis time and real-time factor.

## Current limitations

NeuroAsist v0.3.1 does not provide:

- always-on listening;
- automatic voice activity detection conversations;
- interruption while the character is speaking;
- avatar rendering or lip sync;
- long-term semantic memory or RAG;
- file, shell, browser, screen, or desktop access;
- accounts, remote hosting hardening, or multi-user isolation.

## Project documentation

The current project architecture, long-term concept, and development direction are described in:

- **[Neuro‑VTuber Assistant Blueprint v1.1](Docs/neuro_vtuber_assistant_blueprint_v1.1.md)**

## Planned direction

The project is expected to evolve in stages:

1. stable text and voice interaction;
2. VRM or Unity avatar integration;
3. emotions, animations, and lip sync;
4. controlled development agent and project sandbox;
5. screen context and optional long-term memory;
6. modular multi-agent platform.

The exact plan may change as the prototype is tested and developed.

## License

NeuroAsist is licensed under the [Apache License 2.0](LICENSE).

Third-party models and services may have their own licenses and usage terms. Check the selected Silero model license and the configured LLM provider terms before commercial use.
