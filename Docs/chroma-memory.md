# ChromaDB Memory (V0.7)

Long-term memory remains canonical in SQLite; ChromaDB is a rebuildable semantic index stored by default in `data/chroma`.

Memory extraction runs asynchronously after the visible reply, so it does not add a second DeepSeek wait to chat latency. Before an extraction request, password, code, token, and API-key spans are removed. Other independent facts in the same message are still eligible for memory. A small deterministic safety net preserves only clearly structured response-length preferences, current goals, and the assistant-developer relationship when the extraction model misses them; ambiguous social ties are kept in review rather than injected into context.

Voice input is interpreted conservatively before context, LLM, and memory use: obvious common typos and close matches to names already stored in memory may be repaired. The raw STT transcript remains the original message, while a separate corrected value is indexed and used for continuity. Ambiguous words are not silently changed.

## Flow

1. Context Manager retrieves active memories from FTS and ChromaDB.
2. Relevant compact memories are added to the DeepSeek prompt.
3. The user receives the character reply immediately. Exactly one durable `memory_extract` job then asks DeepSeek for compact memory candidates; this runs for both text and completed live-voice turns.
4. SQLite validates proposals, records provenance/audit, deduplicates and resolves only truly single-value conflicts. A new response-length preference or current goal supersedes an older active value. In balanced mode only high-confidence, durable normal facts are activated. Sensitive or important ambiguous facts are clarified in conversation; no manual review queue exists.
5. Durable SQLite background jobs sync active records to ChromaDB. On crash, pending work is retried at startup.

Live voice retains streaming: its extraction request begins only after the completed turn, so it does not delay speech. The background extractor is the single automatic LLM write path, which prevents a text reply and an extraction job from saving the same ordinary fact twice. A tiny deterministic path remains synchronous only for a name and the well-structured assistant-developer fact, so the UI can acknowledge those high-confidence facts immediately. If asynchronous LLM extraction is disabled, the legacy synchronous deterministic path remains available.

The index is not a source of truth: it can be deleted and rebuilt from the active SQLite records. Existing history is not automatically turned into memories; extraction starts with new turns after the feature is enabled.

## Quality rules

- Store only self-contained, atomic facts. Phrases such as `что ...`, command prefixes, and unclear references are removed or rejected.
- Independent interests and notes coexist; single-value facts such as the user's name, current goal, and desired response length supersede older values.
- A typed relationship is used for known patterns, for example `assistant → developers → Олег и Федя`.
- Ambiguous social links are held for review; automatic activation requires a direct, self-contained statement of the relation.
- Medical facts stay in review even if the model marks them as normal. Passwords, codes, tokens, and other secrets are discarded and never become memories.
- DeepSeek receives examples of good and bad candidates, while backend validation remains the final authority.

## Enable

```env
MEMORY_LLM_EXTRACTION_ENABLED=true
MEMORY_ASYNC_EXTRACTION_ENABLED=true
MEMORY_LLM_MIN_CONFIDENCE=0.70
SEMANTIC_RETRIEVAL_ENABLED=true
SEMANTIC_RETRIEVAL_EVAL_PASSED=true
SEMANTIC_VECTOR_BACKEND=chroma
```

Use `POST /memory/reindex` to rebuild Chroma from SQLite. **Memory Center → Reset all memory and history** irreversibly clears the timeline, summaries, memories, and the rebuildable index. On Windows it marks `data/chroma` for a hard delete at the next backend start, because ChromaDB keeps its vector files open while the current process is running.

For normal development startup use `npm --prefix apps/desktop run dev`; the desktop shell starts Vite and the backend together.

## Current limitation

The initial provider is `hash-multilingual-v1`: it avoids downloading a local model but has modest semantic quality. FTS remains the safe fallback; memory quality still needs an evaluation corpus and further tuning.
