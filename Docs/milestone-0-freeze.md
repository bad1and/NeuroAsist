# V0.5 Milestone 0 — Freeze and reproducibility

This record freezes the behaviour inherited from `v0.4.1`; it deliberately adds no timeline, episode, summary, memory, Tauri, VAD, or protocol-v3 implementation.

## Baseline

- Source branch and immutable commit: `v0.4.1` / `467919ab5b65ed3405cc2f51f0e8aaf53edb741d`.
- Full compatibility metadata: [version-manifest-v0.4.1.json](version-manifest-v0.4.1.json).
- Existing SQLite contract: `messages(id, session_id, role, content, created_at)` with recent-message retrieval ordered by `id`.
- Existing public compatibility identifiers remain untouched, including the `default` session and Avatar Protocol v1/v2.

## Reproducibility assets

- `tests/fixtures/v0.4.1-history.sqlite3` is a deterministic, pre-migration database fixture with two sessions and four messages.
- `scripts/create_v041_history_fixture.py` regenerates that fixture only when the legacy schema changes intentionally.
- `scripts/smoke_v041.ps1` starts the backend and Vite UI on loopback with mock voice providers, checks `/health` and the web entrypoint, then terminates both child processes.
- `scripts/benchmark_tts.py` remains the baseline TTS measurement. The 2026-07-14 local CPU run (`Silero`, `xenia`, 30 phrases, one run) measured 4,135 ms model load, 106.5 ms P50 synthesis, 225.9 ms P95 synthesis, and 0% failures. Store machine-specific output outside Git under `data/`.

## Verification on 2026-07-14

- Python: `106 passed` with `pytest`.
- Web: `2` Vitest files / `9` tests passed; the production Vite build passed.
- Smoke: `scripts/smoke_v041.ps1` started backend and web on loopback using mock STT/TTS, verified both entrypoints, and removed its child-process tree.

## Continuous companion decision

V0.5 is one persistent companion with one shared history. Internal episodes, summaries, long-term memory, and context assembly will be introduced only in later milestones. Separate user-created chats, Dev Agent, sandboxing, filesystem/shell tools, and desktop control are not V0.5 work.

## Unity source handoff

The Unity project was found only as an unpublished local source tree, not as a Git repository. It is therefore not reproducible from a clean clone and cannot truthfully be pinned yet. The target remote `bad1and/NeuroAsistAvatar` was checked on 2026-07-14 and was unavailable. See [unity-source.md](unity-source.md) for the required publish-and-pin procedure. No absolute local path is retained in tracked V0.5 documentation.
