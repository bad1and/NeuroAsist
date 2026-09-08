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
audit events. Ручное создание отключено: факты появляются из разговора, но в
Memory Center пользователь может исправить, закрепить, архивировать и
восстановить запись. «Забыть навсегда» физически удаляет memory item, его
audit/evidence и rebuildable vector; исходную реплику в истории нужно удалять
отдельным явным действием.

## Retrieval

1. Context Manager формирует запрос из текущего user turn и continuity.
2. SQLite FTS даёт безопасный lexical baseline.
3. При включённом и прошедшем eval semantic backend добавляет факты, темы,
   обязательства и сводки прошлых эпизодов.
4. Memory service объединяет результаты, фильтрует inactive/superseded items и ограничивает context token budget.
5. В LLM prompt попадают компактные JSON records с ID, помеченные как данные,
   а не инструкции. `access_count` растёт только если Character Protocol
   подтвердил, что видимый ответ реально использовал этот ID.

В clean install включены background extraction и локальный Chroma/hash-контур;
для них не нужен отдельный секрет или скачивание модели. При ошибке semantic
backend система продолжает работу через FTS. Индексные jobs
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

- `GET /memory/diagnostics` — counts, jobs, policy state и реально активные
  writer/retrieval/backend/provider capabilities;
- `GET /memory/retrieval/explain` — объяснение выбранных результатов;
- `GET /memory/{id}/audit` — provenance/audit конкретной записи;
- `GET /debug/llm/usage` — реальные tokens/cache/retries background extraction.

Release quality оценивается по corpus precision/recall и token cost, а не по
количеству созданных memories. Воспроизводимый локальный gate:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_memory.py
```

Corpus находится в `tests/fixtures/memory_eval.json`; ненулевой exit code
означает, что хотя бы один заявленный threshold не пройден. Требования находятся
в [release-checklist.md](release-checklist.md).
