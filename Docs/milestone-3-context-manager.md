# Milestone 3 — Summarization and Context Manager

Milestone 3 replaces the unbounded recent-history prompt with a bounded continuity context. It deliberately does not introduce long-term memory, embeddings, a desktop shell, or any later V0.5 feature.

## Storage and migration

`TimelineStore` migration **3** adds two additive SQLite tables:

- `episode_summaries` stores versioned, structured summaries with source-message IDs and a supersession marker;
- `background_jobs` persists summary work independently of a chat request.

On startup, all closed, unsummarized episodes—including the V0.4.1 history imported by earlier migrations—receive one `episode_summary` job. Raw messages remain canonical and are never deleted or replaced by the summary.

The first summarizer is deterministic (`prompt_version=deterministic-v1`): it records a compact text, topics, decision-like user statements, open questions, and provenance. This is intentionally a safe baseline before any provider-backed summarizer is introduced. A failed job is retried up to three times with a short exponential delay, then marked `failed`; it never blocks a new message or LLM response.

## Context assembly

`ContextManager` builds the model history used by `CharacterAgent`:

```text
continuity rule
+ rolling summary for older part of current episode
+ relevant closed-episode summaries
+ recent complete user/assistant turns
+ current user message (added by CharacterAgent)
```

The manager applies `CONTEXT_MAX_TOKENS` (a conservative character-count estimate). It preserves the continuity rule and complete recent turns, removing old episode summaries first and then the oldest whole turns. The current user message continues to be appended by `CharacterAgent`, so it is always present. The normal character JSON prompt remains the system identity supplied by the existing agent.

Relevant old summaries are selected by query keywords with a recent-summary fallback. This is lexical baseline retrieval only; semantic retrieval and stable memory belong to Milestones 5–6.

## Runtime and diagnostics

`SummaryWorker` runs after startup as an independent async loop and processes one durable job at a time. The normal text and voice paths do not await it.

Development diagnostics:

- `GET /debug/context/preview?message=...` builds and returns the context, token estimate, selected IDs, and trimming details.
- `GET /debug/context/last` returns diagnostics for the last context built by a chat or voice turn.

`CONTEXT_MANAGER_ENABLED=false` keeps the V0.4-compatible recent-history path. Configuration defaults are in `.env.example`:

```dotenv
CONTEXT_MANAGER_ENABLED=true
CONTEXT_MAX_TOKENS=3000
CONTEXT_RECENT_TURNS=8
```

## Verification

`tests/test_context_summary.py` covers background final summaries, restart continuity, non-blocking failure handling, budget trimming, turn pairing, and the rolling active-episode summary. The existing timeline and agent tests continue to cover the compatibility path.
