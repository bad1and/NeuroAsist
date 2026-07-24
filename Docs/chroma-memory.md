# ChromaDB Memory (V0.6)

Long-term memory remains canonical in SQLite; ChromaDB is a rebuildable semantic index stored by default in `data/chroma`.

## Flow

1. Context Manager retrieves active memories from FTS and ChromaDB.
2. Relevant compact memories are added to the DeepSeek prompt.
3. The user receives the character reply immediately. A durable `memory_extract` job then asks DeepSeek for compact memory candidates; this runs for both text and completed live-voice turns.
4. SQLite validates candidates, records provenance/audit, deduplicates and resolves only truly single-value conflicts. In balanced mode only high-confidence, durable normal facts are auto-activated; sensitive facts remain in review.
5. Durable SQLite background jobs sync active records to ChromaDB. On crash, pending work is retried at startup.

Live voice retains streaming: its extraction request begins only after the completed turn, so it does not delay speech. Explicit `Запомни: ...` commands retain the deterministic fallback as a backup.

The index is not a source of truth: it can be deleted and rebuilt from the active SQLite records. Existing history is not automatically turned into memories; extraction starts with new turns after the feature is enabled.

## Quality rules

- Store only self-contained, atomic facts. Phrases such as `что ...`, command prefixes, and unclear references are removed or rejected.
- Independent explicit notes coexist; only single-value facts such as the user's name and current corrections supersede older values.
- A typed relationship is used for known patterns, for example `assistant → developers → Олег и Федя`.
- DeepSeek receives examples of good and bad candidates, while backend validation remains the final authority.

## Enable

```env
MEMORY_LLM_EXTRACTION_ENABLED=true
MEMORY_LLM_MIN_CONFIDENCE=0.70
SEMANTIC_RETRIEVAL_ENABLED=true
SEMANTIC_RETRIEVAL_EVAL_PASSED=true
SEMANTIC_VECTOR_BACKEND=chroma
```

Use `POST /memory/reindex` to rebuild Chroma from SQLite. **Memory Center → Reset all memory and history** irreversibly clears the timeline, summaries, memories, and the rebuildable index. On Windows it marks `data/chroma` for a hard delete at the next backend start, because ChromaDB keeps its vector files open while the current process is running.

For normal development startup use `npm --prefix apps/desktop run dev`; the desktop shell starts Vite and the backend together.

## Current limitation

The initial provider is `hash-multilingual-v1`: it avoids downloading a local model but has modest semantic quality. FTS remains the safe fallback; memory quality needs further tuning and evaluation.
