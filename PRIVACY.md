# Privacy

Iris is local-first, not fully offline. This document describes the current
source implementation; a distributed build must reproduce these properties.

## Processed locally

- microphone PCM, VAD and configured STT;
- configured TTS and generated playback audio;
- timeline, episodes, character state, memory and audit in SQLite;
- runtime settings, model files, logs and backups;
- Unity avatar rendering;
- Coding Agent files and commands inside the local Docker sandbox.

Raw live microphone audio is held in memory and is not persisted by default.
Diagnostic audio capture must be explicitly enabled and should be treated as
sensitive user data.

## Sent to configured external services

Conversation generation, background memory consolidation, reflections and
optional Coding Agent reasoning send prompts to the configured DeepSeek-
compatible endpoint. Requests may contain the current user message, a bounded
recent context, compact retrieved memories and system instructions required for
the task. Coding Agent uses a separate purpose profile and can use a separate
API key.

Review the endpoint provider's privacy and retention policy before use. Iris
does not make a cloud LLM local merely because STT and TTS are local.

## Storage locations

Installed desktop data is stored under `%LOCALAPPDATA%\NeuroAsist` by default.
See [operations](Docs/operations.md) for the layout. Browser development may
use repository-relative `data/` and `logs/` paths.

Windows Credential Manager stores the desktop API key. `.env` is supported for
development and must never be committed. Runtime settings and backup ZIP files
exclude API keys.

## Diagnostics

LLM telemetry records counts, cache usage, reasoning tokens, latency, status
and errors without storing prompt/response content. Application logs and event
metadata can still reveal filenames, model names, error details or task IDs;
inspect them before sharing.

## User controls

The application exposes memory review/edit/delete, dialog reset, companion data
reset, diagnostic visibility and backup creation. A supported in-app backup
restore is not yet available and remains a release gate.

To remove local data, stop every Iris process first and use the application's
reset controls or remove the chosen data directory intentionally. Uninstall
behaviour and the retain/delete choice must be verified for each public build.

## Coding Agent

Project context is opt-in and restricted to allowed roots/files. The task copy
can be sent to the configured coding model as needed for the objective. Docker
commands have no network and no live source mount; applying reviewed changes to
the source requires an explicit user action.

## Questions

For implementation details, open a repository issue without private data. For
a suspected vulnerability, follow [SECURITY.md](SECURITY.md) instead of posting
secrets or an exploit publicly.
