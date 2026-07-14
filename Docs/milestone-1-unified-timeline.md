# V0.5 Milestone 1 — Versioned storage and unified timeline

Milestone 1 replaces the active V0.4 history path with one canonical companion timeline while preserving the legacy `/chat`, `/voice/chat`, and `session_id` contracts.

## Storage and migration

`TimelineStore` owns `schema_migrations` and migration `1`, which creates:

- `companion_relationships` — the fixed local `primary` relationship (`neuro` / `local_user`);
- `conversation_timelines` — its single `primary-timeline`;
- `conversation_messages` — append-only message rows with role, status, input mode, correction, client id, timestamps, and metadata.

At startup, every row from the V0.4 `messages` table is copied exactly once. The old session identifier is retained as `metadata.legacy_session_id`; it no longer creates a separate conversation. The original table is retained for rollback and compatibility. The V0.4 fixture migration is covered by tests.

`TIMELINE_V2_ENABLED=true` selects the adapter by default. Set it to `false` only to run the legacy storage adapter while investigating a migration issue; Timeline API endpoints then report `503` instead of silently serving split histories.

## Behaviour guarantees

- A client id is unique within the primary timeline. Repeated `POST /timeline/messages` calls return the original row instead of duplicating it.
- Completed text is never overwritten: a transcription correction is stored in `corrected_content`, preserves `original_content`, and marks the row for downstream review.
- Existing `/chat` and `/voice/chat` calls keep accepting `session_id`. With Timeline V2 on, both write to the single primary timeline; voice turns are tagged `input_mode=voice`.
- Pagination has stable chronological output; search is a bounded SQLite `LIKE` baseline. FTS and semantic retrieval are intentionally deferred to Milestones 5 and 6.
- Range deletion is currently physical because summaries and memories do not yet exist. Their dependency-aware deletion policy belongs to later milestones.

## API

| Endpoint | Purpose |
|---|---|
| `GET /timeline` | Primary relationship and timeline metadata |
| `GET/POST /timeline/messages` | Paginated journal rows and idempotent raw append |
| `PATCH /timeline/messages/{id}` | Append-only correction |
| `POST /timeline/stop?message_id=` | Mark a stored message cancelled |
| `GET /timeline/journal` | Date grouping for the Journal UI |
| `GET /timeline/search?q=` | Bounded history search |
| `DELETE /timeline/range` | Explicitly bounded history deletion |

The React panel restores the latest timeline messages at startup and has a Journal tab with date groups, search, refresh, and explicit range deletion. The existing voice stop control remains available; a failed text request restores a Retry action without leaving an optimistic-only user message in the panel. It has no user-created chat list.

## Verification

`tests/test_timeline_v2.py` covers legacy migration, one timeline, idempotent append, correction provenance, search, pagination, journal grouping, and bounded deletion. Existing API and voice tests remain part of the full suite.
