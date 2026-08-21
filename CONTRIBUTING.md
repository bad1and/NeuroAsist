# Contributing

Iris is developed primarily on Windows. Before changing code, read
[Architecture](Docs/architecture.md), [Operations](Docs/operations.md) and the
README for the subsystem you are touching.

## Setup and verification

Use the pinned Python/Node dependencies from the root README. Before submitting
a change, run the checks proportional to its scope; for a cross-cutting change:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/desktop run check
.\.venv\Scripts\python.exe scripts/check_docs.py
```

## Change rules

- Preserve user data and migration compatibility.
- Never add a host-shell fallback for Coding Agent.
- Keep desktop core on loopback with token authentication.
- Do not persist raw microphone audio by default.
- Keep SQLite canonical; semantic indexes must remain rebuildable.
- Update EN/RU README and current subsystem docs together when behaviour changes.
- Do not rewrite protocol/schema/migration versions during an application version bump.
- Add regression coverage for lifecycle, persistence and concurrency fixes.

## Documentation

Current documents live directly under `Docs/`; old branch-specific plans belong
under `Docs/archive/`. Every local Markdown link in maintained docs must resolve.
Update `CHANGELOG.md` for user-visible changes.

## Secrets and generated files

Do not commit `.env`, API keys, databases, logs, model caches, diagnostic audio,
Unity builds, node_modules, Python environments or signing material. Keep
experiments isolated from production dependencies and label their README as
historical/experimental.
