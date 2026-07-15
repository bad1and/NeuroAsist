# ChromaDB Memory (V0.6)

Long-term memory remains canonical in SQLite; ChromaDB is a rebuildable semantic index stored by default in `data/chroma`.

## Flow

1. Context Manager retrieves active memories from FTS and ChromaDB.
2. Relevant compact memories are added to the DeepSeek prompt.
3. One DeepSeek response returns the character reply and optional `memory_candidates`.
4. SQLite validates candidates, records provenance/audit, deduplicates and resolves only truly single-value conflicts.
5. A durable SQLite background job syncs active records to ChromaDB. On crash, pending work is retried at startup.

Live voice retains streaming. Explicit `Запомни: ...` commands use the deterministic fallback after the turn without a second LLM request.

## Enable

```env
MEMORY_LLM_EXTRACTION_ENABLED=true
MEMORY_LLM_MIN_CONFIDENCE=0.70
SEMANTIC_RETRIEVAL_ENABLED=true
SEMANTIC_RETRIEVAL_EVAL_PASSED=true
SEMANTIC_VECTOR_BACKEND=chroma
```

Use `POST /memory/reindex` to rebuild Chroma from SQLite. **Memory Center → Reset all memory and history** irreversibly clears the timeline, summaries, memories, and the rebuildable index.

## Current limitation

The initial provider is `hash-multilingual-v1`: it avoids downloading a local model but has modest semantic quality. FTS remains the safe fallback; memory quality needs further tuning and evaluation.
