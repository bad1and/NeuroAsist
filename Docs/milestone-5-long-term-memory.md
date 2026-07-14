# Milestone 5 — Long-Term Memory V1

Milestone 5 adds a controlled durable-memory layer on top of the single timeline and its episodes. It deliberately does not add embeddings, vector storage, sqlite-vec, an embedding provider, or semantic rank fusion; those belong to Milestone 6.

## Data and provenance

SQLite migration V4 creates `memory_items`, `memory_audit`, and FTS5 indexes for memories, episode summaries, and raw timeline messages. A memory contains a scope, type, canonical text, confidence, importance, sensitivity, lifecycle status, source episode and source user-message IDs. Every automatic or manually added memory must cite an existing user message. The audit records candidate creation, activation, edits, confirmation, rejection, supersession, deletion, restoration, and retrieval.

## Policy and retrieval

`MemoryService` is the only writer of canonical memory. It extracts conservative candidates from user messages (explicit remember requests and stable identity/preference statements), validates sources, limits automatic extraction to three candidates per turn, deduplicates exact facts, and supersedes a conflicting active fact instead of silently overwriting it. Modes are `off`, `ask`, and `automatic`; sensitive candidates remain confirmation-gated by default.

Retrieval is FTS5-first plus a small exact-profile strategy, and only `active` memories may enter `ContextManager`. Retrieval is recorded in audit and context diagnostics expose `selected_memory_ids` and dropped memory IDs. Deleted, rejected, superseded, and incognito memories cannot leak into context.

## Privacy and UI

Runtime settings expose memory mode and an incognito switch. In incognito, chat/voice turns are not appended to the timeline, memory extraction and retrieval are disabled, and no episode summary can be created from that turn. The React **Memory Center** supports filtering/search, candidate confirmation/rejection, provenance/audit display, forgetting/restoration, verified manual entry, FTS reindexing through the API, and memory-only clearing. Clearing memory does not delete timeline history.

## API

`GET/POST /memory`, `PATCH/DELETE /memory/{id}`, `POST /memory/{id}/restore`, `confirm`, `reject`, `POST /memory/reindex`, `POST /memory/clear`, and `GET /memory/{id}/audit` are available. The Memory Center passes normal desktop authentication through the existing API client.

## Verification

`tests/test_long_term_memory.py` covers source validation, FTS/profile retrieval, deduplication, conflict supersession, sensitive confirmation, deletion leakage prevention, independent clear, and incognito. Existing timeline and context regression tests continue to pass, as does the web TypeScript/Vite build.
