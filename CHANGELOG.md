# Changelog

Notable user-visible changes are recorded here. The project follows Semantic
Versioning; historical experimental branches before 1.0 were not published as
stable releases.

## [1.0.0] - Unreleased

### Added

- Tauri 2 desktop lifecycle with tray, single instance, safe mode, protected
  random loopback port and Windows Credential Manager integration.
- Continuous live voice input with PCM16 AudioWorklet transport, VAD, Smart
  Turn, barge-in and reconnect-safe generation ownership.
- Unified timeline, episodes, summaries, long-term memory provenance/audit,
  Memory Center and optional semantic retrieval.
- Character Protocol v3, mood/relationship state, reflections and Unity VRM
  avatar placement as desktop overlay or embedded chat surface.
- Optional Docker-only Coding Agent with isolated workspaces, durable task
  queue, logs, diff, conflict detection and explicit review/apply.
- Purpose-level LLM token limits, retry budgets and content-free usage/cache/
  reasoning telemetry.
- GitHub regression CI, weekly one-hour synthetic lifecycle soak and a protected
  Windows release-candidate workflow with SHA-256 manifest generation.

### Changed

- Memory extraction is coalesced and gated instead of calling the LLM after
  every turn.
- Character prompts use a compact stable prefix and separate dynamic state for
  better cache reuse.
- Runtime settings are persisted atomically before live publication.
- Blocking SQLite/filesystem operations were removed from interactive async
  hot paths.
- Product metadata and public documentation now use `1.0.0` consistently.
- Desktop packaging token-smokes the PyInstaller sidecar and scans package
  staging resources for private runtime files before NSIS packaging.
- The NSIS candidate keeps the CPU PyTorch runtime used by the default voice
  profile; CUDA distribution requires a separately qualified GPU add-on.

### Fixed

- Model installation could deadlock on a duplicate request.
- Background workers could stop permanently after an unexpected exception.
- Voice STT/LLM/TTS tasks could outlive disconnect/reconnect and publish stale
  results.
- Concurrent settings writers could lose changes or expose a partial update.

### Known release gates

- Supported backup restore workflow.
- Clean Windows VM installer/upgrade/uninstall rehearsal.
- Real one-hour voice/avatar soak and memory/persona quality evaluation.
- Full dependency/model/asset license audit and signed release artifact.

See [Docs/release-checklist.md](Docs/release-checklist.md).
