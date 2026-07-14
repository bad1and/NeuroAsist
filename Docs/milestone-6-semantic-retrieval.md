# Milestone 6 — Semantic Retrieval

Milestone 6 extends — but never replaces — the FTS5 retrieval baseline from Milestone 5. It does not introduce Character Protocol v3, avatar behaviour, VAD, or any Milestone 7+ functionality.

## Vector contract and persistence

`apps/backend/app/semantic` defines the asynchronous `VectorIndex` contract plus `NullVectorIndex` and `SqliteVecIndex`. The SQLite adapter records namespace, model ID, dimension, vector payload, and update time in migration V5 tables. `memory` and `episode_summary` have separate namespaces. A model or dimension change is rejected until that namespace is rebuilt, so incompatible vectors are never mixed.

The optional `sqlite-vec` Python extension is detected when present. The current portable adapter keeps a rebuildable SQLite vector store and evaluates cosine similarity in-process when that extension is not installed. This preserves the same isolation contract without blocking startup or adding a heavyweight runtime dependency. Canonical memories and summaries remain normal SQLite rows; FTS5 remains available throughout.

## Providers, fusion and fallback

`HashEmbeddingProvider` is a deterministic multilingual n-gram projection that implements the embedding provider contract without a model download. It is a conservative fallback rather than a claimed trained semantic model. A production embedding provider can replace it without changing the index API.

Retrieval combines FTS rank, semantic cosine score, importance, confidence, and a temporal-query signal. Each returned memory carries `retrieval.score`, component scores, and reasons. `/memory/retrieval/explain?q=…` and Context Manager diagnostics expose this explanation. Any vector error marks semantic retrieval degraded for the running process and continues with FTS rather than blocking a reply.

## Safety gate and rebuild

Semantic retrieval is off by default. It requires both `SEMANTIC_RETRIEVAL_ENABLED=true` and `SEMANTIC_RETRIEVAL_EVAL_PASSED=true`; the latter is an explicit quality gate after comparing the multilingual benchmark against FTS-only retrieval. `POST /memory/reindex` preserves its former `indexed` field and additionally reports FTS/semantic index counts and semantic state. It rebuilds active memories and current episode summaries.

## Verification

`tests/test_semantic_retrieval.py` covers multilingual hybrid retrieval, explanation, index rebuilding, model/dimension isolation, strict benchmark gating, and FTS fallback after a vector failure. Full backend and web regressions remain required before release.
