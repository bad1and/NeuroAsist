<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="Docs/media/readme/header.en.dark.png">
    <img src="Docs/media/readme/header.en.light.png" width="900" alt="Iris — an assistant you can talk to. Watercolour irises on either side">
  </picture>

# Iris

A voice assistant for Windows: talk through an idea, work through a problem, or just have a conversation.<br>
Iris remembers useful details from your conversations; an optional avatar can sit beside the dialogue.

[Русский](README.md) · **English** · [Documentation](Docs/index.md)

[![Source version](https://img.shields.io/badge/version-1.0.0-695B86?style=flat-square)](VERSION) · [Apache 2.0](LICENSE)

[Features](#features) · [Interface](#interface) · [Getting started](#getting-started) · [Data](#data) · [Development](#development)

</div>

[![Iris overview: start a conversation, return to the latest chat, view memory and system status](Docs/media/readme/overview.png)](Docs/media/readme/overview.png)

<sub>Home screen</sub>

Speech recognition and synthesis run on your computer. Replies come from an external model, so conversations need internet access and an API key for your chosen provider.

For now, Iris runs from source. [Release status](Docs/MILESTONES.md).

## Features

**Conversation.** Write to Iris or talk to her. In voice mode, she detects the end of your turn; you can interrupt a spoken reply. [Voice conversations](Docs/live-conversation.md).

**Memory.** Iris keeps useful details from your conversations. You can read, edit or delete records in the memory section. [How memory works](Docs/chroma-memory.md).

**Search.** Iris can search when you need to check information or find news. Results and sources stay in history. Search notifications are off by default. [Search and news](Docs/awareness.md).

**Avatar.** An optional Unity avatar can appear on your desktop or inside the dialogue window. Lip movement and gestures accompany speech. [Avatar setup](apps/avatar-unity/README.md).

**Coding Agent.** A separate agent handles coding tasks in Docker. You can review changes before bringing them into your project. It requires Docker and its own API key. [Setup and access boundaries](Docs/coding-agent.md).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="Docs/media/readme/interface.en.dark.png">
    <img src="Docs/media/readme/interface.en.light.png" width="900" alt="What Iris looks like">
  </picture>
</p>

## Interface

### Dialogue

[![Iris Windows app: Unity avatar, reply subtitles, message input and voice controls](Docs/media/readme/dialogue.png)](Docs/media/readme/dialogue.png)

Write a message, start a voice conversation or read reply subtitles here. You can turn the avatar off.

### Memory

[![Iris memory: prepared records about late-night edits, short replies and plans](Docs/media/readme/memory.png)](Docs/media/readme/memory.png)

Records from conversations show the message Iris learned them from.

<details>
<summary>History</summary>

[![Iris history: conversation list and messages from the selected dialogue](Docs/media/readme/history.png)](Docs/media/readme/history.png)

Your conversations, with search across messages.

</details>

<details>
<summary>State</summary>

[![Iris state: mood and relationship state](Docs/media/readme/state.png)](Docs/media/readme/state.png)

Iris's mood and relationship with the person she is talking to.

</details>

<details>
<summary>Voice settings</summary>

[![Iris voice settings: language, voice and playback options](Docs/media/readme/voice-settings.png)](Docs/media/readme/voice-settings.png)

Microphone and output device selection is in the separate devices section.

</details>

<details>
<summary>Coding Agent</summary>

[![Coding Agent: task section with no jobs running](Docs/media/readme/coding.png)](Docs/media/readme/coding.png)

Agent tasks, file changes and execution logs. There are no tasks in this screenshot yet.

</details>

<sub>Screenshots use the Russian interface and a separate profile with prepared conversation and memory examples.</sub>

## Getting started

Running from source requires **Windows 10 or 11**, Git, **Python 3.12**, **Node.js 24 / npm 11**, and FFmpeg and FFprobe in your `PATH`. The Tauri shell also needs Rust 1.77.2 or newer, Microsoft C++ Build Tools and WebView2 Runtime.

### Install dependencies

```powershell
git clone https://github.com/bad1and/NeuroAsist.git Iris
cd Iris

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

npm ci
npm ci --prefix apps/web
npm ci --prefix apps/desktop

Copy-Item .env.example .env
```

For CUDA, install the profile below before `requirements.txt`. [More on dependencies](Docs/dependencies.md).

### Open Iris

```powershell
npm --prefix apps/desktop run dev
```

The shell starts the interface and local backend for you. Save your dialogue model key in **Settings → System → API keys** (**Настройки → Система → API-ключи** in the Russian interface). Keys are stored in Windows Credential Manager; `.env` is for non-secret configuration.

You can start with a text conversation. For voice, wait for the speech models to load and select your microphone and output device. Downloading the models requires internet access and disk space.

To exit completely, choose **Quit** from the Iris icon's menu in the Windows notification area. [First launch and everyday use](Docs/user-guide.md).

<details>
<summary>CUDA — faster speech recognition</summary>

An NVIDIA GPU can accelerate speech recognition. Install the CUDA profile before `requirements.txt`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/torch-cu128.txt
```

If CUDA is unavailable, set `VOICE_STT_DEVICE=cpu` in `.env`. The standard TeraTTSv2 synthesis profile runs on the CPU.

</details>

<details>
<summary>Unity — rebuilding the avatar</summary>

Tauri automatically finds the local avatar build. Unity 2022.3.62f3 is only needed to rebuild it after changes:

```powershell
$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\2022.3.62f3\Editor\Unity.exe'
npm --prefix apps/desktop run build:avatar
```

[Building and configuring the Unity avatar](apps/avatar-unity/README.md).

</details>

<details>
<summary>Docker — the Coding Agent environment</summary>

Start Docker Desktop and build the image:

```powershell
docker build -t neuroasist-coding:latest -f apps/backend/docker/coding.Dockerfile apps/backend/docker
```

Save a separate Coding API key in the app settings and enable the agent. It does not use the dialogue model key. [Full instructions](Docs/coding-agent.md).

</details>

<details>
<summary>Browser mode — interface and backend development</summary>

In two PowerShell windows:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
npm --prefix apps/web run dev
```

Interface: `http://127.0.0.1:5173`. API documentation: `http://127.0.0.1:8000/docs`.

Browser mode does not receive keys from Windows Credential Manager. Launch through Tauri to make model requests.

</details>

If the app will not start or you cannot hear the voice, begin with [troubleshooting](Docs/operations.md#диагностика).

## Data

History, memory and settings stay on your computer. When launched through Tauri, they are stored in `%LOCALAPPDATA%\NeuroAsist`. Microphone audio is not saved by default.

To reply, the model receives your request text and selected conversation context. Search contacts external sources. [More on data](PRIVACY.md).

Deleting a memory record and deleting its source message are separate actions. You can create backups in settings; restoring them through the interface is not available yet. Iris does not provide general desktop control, and Coding Agent runs in its own isolated environment.

[Security](SECURITY.md) · [Project status](Docs/MILESTONES.md) · [Release requirements](Docs/release-checklist.md)

## Development

| Directory | Contents |
| :--- | :--- |
| `apps/web` | React interface |
| `apps/backend` | Conversation, speech, memory and local API |
| `apps/desktop` | Windows shell built with Tauri |
| `apps/avatar-unity` | Optional Unity avatar |
| `apps/protocol` | Shared character and avatar contracts |
| `Docs`, `scripts`, `tests` | Documentation, tools and checks |

Main checks, run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/desktop run check
.\.venv\Scripts\python.exe scripts/check_docs.py
```

[Documentation](Docs/index.md) · [Architecture](Docs/architecture.md) · [Contributing](CONTRIBUTING.md) · [Iris design](design.md)

The version comes from `VERSION`. Installer builds and pre-publication checks are described in [operations](Docs/operations.md) and the [release runbook](Docs/release-runbook.md). Linked subsystem guides are currently in Russian.

<p align="center">
  <a href="Docs/media/readme/poster-less-noise.png"><img src="Docs/media/readme/poster-less-noise.png" width="260" alt="Less noise, more thought poster"></a>
  <a href="Docs/media/readme/poster-always-with-you.png"><img src="Docs/media/readme/poster-always-with-you.png" width="260" alt="Futuristic IRIS poster — Always with you"></a>
  <a href="Docs/media/readme/poster-assistant-project.png"><img src="Docs/media/readme/poster-assistant-project.png" width="260" alt="Assistant Project: Iris poster"></a>
</p>

---

The code is licensed under [Apache 2.0](LICENSE). Models, the avatar and other third-party materials have their own terms: [inventory and provenance](THIRD_PARTY_ASSETS.md).

[Documentation](Docs/index.md) · [Changelog](CHANGELOG.md) · [Русский](README.md) · [Back to top](#iris)
