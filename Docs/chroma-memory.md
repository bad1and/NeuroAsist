# Memory и semantic retrieval

SQLite остаётся единственным каноническим хранилищем долгосрочной памяти Iris.
ChromaDB или другой vector backend — перестраиваемый поисковый индекс, который
можно удалить без потери memory records, provenance или audit trail.

## Запись памяти

Visible reply не ждёт отдельный memory LLM call. После сохранения пользовательского
хода deterministic gate решает, нужен ли background consolidation:

1. Small talk и сообщения без durable cues пропускаются.
2. Уже покрытые high-precision facts не отправляются повторно.
3. Обычные eligible turns объединяются в один trailing window вместо job на каждый ход.
4. Явные user cues — просьба запомнить, correction или goodbye — могут сделать job доступной сразу.
5. Background worker анализирует user deltas в жёстком input budget и получает только небольшой релевантный shortlist тем.
6. Proposal проходит schema validation, policy, confidence/importance gates, deduplication и conflict handling до записи.

Один coalesced job имеет тип `memory_consolidation`. Повторные сообщения до
deadline обновляют существующий pending job, а не создают независимые requests.
Assistant text не используется как источник новых пользовательских фактов.

Sensitive/ambiguous memory следует выбранному режиму и может потребовать
уточнения. Каждый сохранённый объект содержит source IDs, extractor version и
audit events; пользователь может редактировать, подтверждать, отклонять,
архивировать и восстанавливать memory items через Memory Center/API.

## Retrieval

1. Context Manager формирует запрос из текущего user turn и continuity.
2. SQLite FTS даёт безопасный lexical baseline.
3. При включённом и прошедшем eval semantic backend добавляет кандидаты.
4. Memory service объединяет результаты, фильтрует inactive/superseded items и ограничивает context token budget.
5. В LLM prompt попадает компактный memory block, а не полные записи/audit.

При ошибке semantic backend система продолжает работу через FTS. Индексные jobs
durable; status и reindex доступны через `/memory/index/status` и
`/memory/reindex`.

## Основные настройки

Статические defaults находятся в [.env.example](../.env.example), runtime policy
— в Settings → Memory. Ключевые параметры:

- `MEMORY_ENABLED`;
- `MEMORY_MODE` и `MEMORY_SENSITIVE_MODE`;
- `MEMORY_CONTEXT_MAX_TOKENS`;
- `MEMORY_ASYNC_EXTRACTION_ENABLED`;
- `MEMORY_AUTO_MIN_CONFIDENCE` / `MEMORY_AUTO_MIN_IMPORTANCE`;
- `SEMANTIC_RETRIEVAL_ENABLED` / `SEMANTIC_RETRIEVAL_EVAL_PASSED`;
- `SEMANTIC_VECTOR_BACKEND`, embedding provider/model/dimension и retrieval limit.

## Диагностика

- `GET /memory/diagnostics` — counts, jobs и policy state;
- `GET /memory/retrieval/explain` — объяснение выбранных результатов;
- `GET /memory/{id}/audit` — provenance/audit конкретной записи;
- `GET /debug/llm/usage` — реальные tokens/cache/retries background extraction.

Release quality оценивается по corpus precision/recall и token cost, а не по
количеству созданных memories. Требования находятся в
[release-checklist.md](release-checklist.md).
