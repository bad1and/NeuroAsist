# Archive: NeuroAsist V0.6 — Graph Memory System & Local LLM
### Historical proposal; not the current implementation plan

> [!WARNING]
> This document is preserved as an archive of an early graph-memory proposal.
> It is **not** the active V0.7 architecture: NeuroAsist does not use Ollama,
> Natasha, spaCy, Qwen, or a graph schema. Do not implement the sections below
> without a new approved design decision.

## Implemented memory plan (V0.7)

### Goal

Build useful, automatic companion memory without adding a second DeepSeek wait
to the visible reply. The canonical store must remain inspectable and editable,
and semantic search must be rebuildable.

### Implemented flow

```text
User message
  -> Context Manager retrieves active SQLite/Chroma memories
  -> relevant compact context goes into the character request
  -> user receives the reply (or live text/audio stream)
  -> durable background memory_extract job calls DeepSeek once
  -> policy validates/deduplicates candidates in SQLite
  -> active records are indexed in ChromaDB
```

Typed input uses the same live LLM/TTS channel as voice input, but enters it
directly and never performs STT.

### Storage and retrieval

- **SQLite** is the source of truth: timeline, episodes, memory records,
  provenance, status, audit log, conflict/supersession state, and durable jobs.
- **ChromaDB** is a rebuildable semantic index of active records. SQLite FTS is
  retained as a fallback.
- Memory Center lets the user confirm, reject, edit, delete, restore, reindex,
  or fully reset memory and conversation data.

### Extraction policy

- Runs after the visible reply for text and completed live-voice turns.
- Saves only self-contained, future-useful facts: identity, preferences, goals,
  projects, relationships, constraints, skills, decisions, and corrections.
- Passwords, codes, tokens, and API keys are removed before the extraction
  prompt. Other independent facts from the same message are still processed.
- Voice input receives a conservative pre-LLM interpretation: clear common
  typos and close matches to already known names can be repaired, while the raw
  STT transcript remains available for audit. Ambiguous words are left intact.
- Sensitive medical, financial, address, and political data stays in review.
- A narrow deterministic safety net covers a stated response-length preference,
  current goal, and the assistant-developer relationship when extraction misses
  them.
- Ambiguous social relations are held for review; legacy ambiguous active links
  are moved out of prompt context on startup. User-locked records are untouched.
- Single-value facts (name, current goal, response-length preference) supersede
  older active values; independent interests and notes can coexist.

### Current quality boundary

Memory is intentionally conversational and may retain some temporary context if
the model classifies it as durable. The current version favours useful,
inspectable recall over aggressive filtering; Memory Center remains the final
user control. Future work should be guided by a labelled evaluation corpus,
not by adding a local LLM by default.

### Verification

- Backend test suite: `216 passed` at the V0.7 memory/live-text milestone.
- Web build: `npm.cmd --prefix apps/web run build`.
- `POST /memory/reindex` rebuilds Chroma from SQLite.

---

## Контекст и цель

Текущая система памяти (V0.5, [`memory/service.py`](file:///C:/Users/Romanov/.gemini/antigravity/worktrees/NeuroAsist/refactor-ai-graph-memory/apps/backend/app/memory/service.py)) использует детерминированное извлечение на regex-паттернах. Она умеет запоминать имя, предпочтения и явные инструкции (`запомни:`), но не понимает **отношения между сущностями** и не умеет отвечать на вопросы вида «кто такой X», «что связывает X и Y», «когда произошло Z».

**Цель V0.6** — надстроить над существующей системой **темпоральный граф знаний** с локальной LLM для извлечения сущностей и связей, с сохранением всей надёжности V0.5.

> [!IMPORTANT]
> **Ключевые решения (зафиксированы):**
> - **Ollama — обязательная зависимость.** При недоступности Ollama граф-извлечение деградирует до Natasha-only (Tier 1 NER), но не падает.
> - **Только новые сообщения.** Retroactive processing старой истории — не в объёме V0.6.
> - **Средняя детализация.** Извлекаем: людей, события, места, важные факты, которые могут пригодиться в будущем. Не извлекаем: мелкие детали, погоду, одноразовые факты.
> - **KùzuDB — не использовать** (архивирован в конце 2025). График-данные хранятся в SQLite через дополнительные таблицы (graph-in-SQLite).

---

## Анализ железа и VRAM-бюджет

| Компонент | VRAM | Режим |
|-----------|------|-------|
| GTX 1660 Super | **6.0 GB** | Общий бюджет |
| Whisper (STT, запущен постоянно) | ~0.5–1.5 GB | Постоянно |
| **Свободно для Qwen** | **~4.5–5.5 GB** | При активном STT |
| Qwen2.5-7B Q4_K_M | 4.7 GB | В бюджет входит ✅ |
| Qwen2.5-3B Q4_K_M | 2.0 GB | В бюджет входит ✅ |

> [!NOTE]
> **Рекомендация: Qwen2.5-7B Q4_K_M** как основная extraction-модель. Если Whisper нагружен и происходит нехватка VRAM — Ollama автоматически частично офлоадит слои в RAM (32 GB RAM достаточно). Альтернатива — `num_gpu_layers` понижается автоматически.

---

## Источники (исследование завершено)

| Проект | Что взяли |
|--------|-----------|
| **Graphiti / Zep** (arXiv:2501.13956) | Трёхслойная иерархия, bi-temporal модель рёбер |
| **Mem0 / Mem0ᵍ** | Conflict detection, supersession chain |
| **LightRAG** | Incremental indexing, hybrid retrieval |
| **Natasha NLP** | Russian NER без BERT, CPU-only |
| NEREL / RURED datasets | Benchmarks для Russian IE |

---

## Архитектура памяти V0.6

### Три слоя (по Graphiti)

```
┌──────────────────────────────────────────────────────────────────┐
│  СЛОЙ 3: Community Layer (V0.6.1+, не в этом объёме)            │
│  Кластеры сущностей + автогенерируемые summary по темам          │
└──────────────────────────────────────────────────────────────────┘
         ↑ будущее расширение
┌──────────────────────────────────────────────────────────────────┐
│  СЛОЙ 2: Entity Graph (CORE — реализуем в V0.6)                  │
│  Узлы: Person, Place, Event, Concept, Preference, Goal           │
│  Рёбра: KNOWS, WORKS_AT, LIKES, HAPPENED_AT, WANTS…             │
│  Хранится в SQLite (graph_nodes + graph_edges)                   │
│  Каждое ребро имеет valid_from / valid_until (bi-temporal)       │
└──────────────────────────────────────────────────────────────────┘
         ↑ извлекается локальной LLM из каждого нового эпизода
┌──────────────────────────────────────────────────────────────────┐
│  СЛОЙ 1: Episode Store (СУЩЕСТВУЮЩИЙ — не трогаем)               │
│  SQLite: timeline_messages + episode_summaries                   │
│  Неизменяемый журнал — источник истины                           │
└──────────────────────────────────────────────────────────────────┘
```

### Что извлекаем (средняя детализация)

**Извлекаем:**
- 👤 Люди: имена, прозвища, роли (`Дима — коллега`, `мама`, `Лена из универа`)
- 📍 Места: дом, работа, города, любимые заведения
- 📅 События: встречи, дни рождения, важные даты, совместные активности
- 💡 Предпочтения: что любит/не любит (`любит кофе`, `ненавидит опенспейс`)
- 🎯 Цели и планы: проекты, планы на ближайшее время
- 🏷️ Факты о пользователе: профессия, интересы, текущая жизненная ситуация

**НЕ извлекаем:**
- ❌ Единичные мелкие факты без контекста (`сегодня было холодно`)
- ❌ Технические детали разговора
- ❌ Повторения уже известного без новой информации
- ❌ Метаданные о самом чате

---

## Схема данных

### Новые таблицы SQLite

```sql
-- УЗЛЫ ГРАФА: именованные сущности
CREATE TABLE IF NOT EXISTS graph_nodes (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    type        TEXT NOT NULL CHECK(type IN (
                    'Person', 'Place', 'Event', 'Concept',
                    'Preference', 'Goal', 'Artifact', 'Constraint'
                )),
    canonical_name TEXT NOT NULL,        -- нормализованное имя (нижний регистр)
    display_name   TEXT NOT NULL,        -- отображаемое имя (оригинальный регистр)
    aliases        TEXT DEFAULT '[]',    -- JSON array псевдонимов
    properties     TEXT DEFAULT '{}',   -- JSON: доп. атрибуты (профессия, роль и т.д.)
    importance     REAL DEFAULT 0.5,     -- 0.0–1.0, влияет на retrieval ranking
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- РЁБРА ГРАФА: отношения с темпоральными метками
CREATE TABLE IF NOT EXISTS graph_edges (
    id           TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    source_id    TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    rel_type     TEXT NOT NULL CHECK(rel_type IN (
                    'KNOWS', 'WORKS_AT', 'LIVES_IN', 'PARTICIPATED_IN',
                    'LIKES', 'DISLIKES', 'WANTS', 'INTERESTED_IN',
                    'HAPPENED_AT', 'RELATED_TO', 'IS_FRIEND_OF',
                    'IS_FAMILY_OF', 'IS_COLLEAGUE_OF', 'HAS_GOAL'
                )),
    target_id    TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    -- bi-temporal модель (по Graphiti/Zep):
    valid_from   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    valid_until  TEXT,                  -- NULL = факт актуален сейчас
    -- provenance:
    episode_id   TEXT,                  -- из какого эпизода извлечён факт
    source_msg_id TEXT,                 -- ID конкретного сообщения
    -- качество:
    confidence   REAL DEFAULT 0.7,      -- 0.0–1.0
    properties   TEXT DEFAULT '{}',     -- JSON: доп. свойства рёбра (role, context, etc.)
    superseded_by TEXT,                 -- ID нового ребра, если этот факт устарел
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- FTS5 ИНДЕКС для полнотекстового поиска по сущностям
CREATE VIRTUAL TABLE IF NOT EXISTS graph_nodes_fts USING fts5(
    node_id UNINDEXED,
    canonical_name,
    display_name,
    aliases,
    content='graph_nodes',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

-- ФЛАГ обработки на уровне эпизодов
ALTER TABLE episodes ADD COLUMN graph_processed INTEGER NOT NULL DEFAULT 0;

-- ИНДЕКСЫ для производительности
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_temporal ON graph_edges(valid_from, valid_until);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON graph_nodes(type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_canonical ON graph_nodes(canonical_name);
```

---

## NLP-пайплайн (трёхступенчатый)

```
Новое сообщение пользователя (завершён эпизод)
  │
  ├─► [Tier 1] NatashaExtractor  ← CPU, <10ms, ВСЕГДА работает
  │       natasha NER: PER / LOC / ORG
  │       Если нет сущностей → СТОП (LLM не вызываем)
  │
  ├─► [Tier 2] spaCy ru_core_news_lg  ← CPU, <50ms
  │       Dependency parsing, лемматизация
  │       Контекст для relation extraction
  │
  └─► [Tier 3] Qwen2.5-7B via Ollama  ← GPU, ~3–8s
          Relation extraction в JSON
          Confidence scoring
          Только если Tier 1 нашёл сущности
          Только для эпизодов с достаточной информацией
```

### Промпт-шаблоны (зафиксированы)

**System prompt для извлечения сущностей (Tier 3, Pass 1):**
```
Ты — система извлечения знаний из разговора с ИИ-компаньоном.
Твоя задача — найти ЗНАЧИМЫЕ сущности, которые важно запомнить.

Категории:
- Person: имена людей, прозвища, роли (мама, коллега, друг)
- Place: места (город, работа, дом, заведение)
- Event: события, встречи, даты, праздники
- Concept: темы, хобби, профессиональные области
- Preference: что любит/не любит пользователь
- Goal: планы, цели, задачи

НЕ извлекай: мелкие бытовые детали, технические команды, одноразовые факты.

Верни ТОЛЬКО JSON, без пояснений:
{"entities": [{"text": "...", "type": "Person|Place|Event|Concept|Preference|Goal", "canonical": "...", "importance": 0.0-1.0}]}
```

**System prompt для извлечения отношений (Tier 3, Pass 2):**
```
Ты — система извлечения отношений из разговора.
Тебе дан текст и список уже найденных сущностей.
Найди отношения ТОЛЬКО между этими сущностями.
Субъект отношения — всегда пользователь (если не указано иное).

Допустимые типы отношений:
KNOWS(person)         — пользователь знает этого человека
IS_FRIEND_OF(person)  — является другом
IS_FAMILY_OF(person)  — является родственником
IS_COLLEAGUE_OF(person) — коллега
WORKS_AT(place/org)   — работает там
LIVES_IN(place)       — живёт там
LIKES(entity)         — любит/нравится
DISLIKES(entity)      — не любит/раздражает
WANTS(goal)           — хочет/планирует
INTERESTED_IN(concept) — интересуется темой
PARTICIPATED_IN(event) — участвовал/участвует

Верни ТОЛЬКО JSON:
{"relations": [{"subject": "user", "relation": "ТИП", "object": "canonical_name сущности", "confidence": 0.0-1.0, "context": "краткая фраза-пояснение"}]}
```

---

## Структура файлов

### Новые файлы

```
apps/backend/app/
├── memory/
│   ├── service.py               [MODIFY] — добавить граф-ретривл, feature flag
│   ├── graph/
│   │   ├── __init__.py          [NEW]
│   │   ├── schema.py            [NEW] — DDL миграция, константы типов
│   │   ├── store.py             [NEW] — GraphMemoryStore: CRUD + запросы
│   │   ├── extractor.py         [NEW] — GraphExtractor: NLP pipeline
│   │   ├── deduplicator.py      [NEW] — EntityDeduplicator: fuzzy matching
│   │   ├── worker.py            [NEW] — GraphExtractorWorker: asyncio queue
│   │   └── retriever.py         [NEW] — GraphRetriever: context formatter
│   └── nlp/
│       ├── __init__.py          [NEW]
│       └── natasha_ner.py       [NEW] — NatashaExtractor: Tier 1 NER
├── storage/
│   └── timeline.py              [MODIFY] — добавить graph_processed колонку
├── context/
│   └── (builder или manager)    [MODIFY] — добавить GRAPH_CONTEXT блок
└── api/
    └── (memory router)          [MODIFY] — новые эндпоинты для граф-сущностей
```

---

## Детальные спецификации компонентов

---

### `apps/backend/app/memory/graph/schema.py`

```python
"""
Константы схемы графа и DDL для миграции SQLite.
"""

GRAPH_NODE_TYPES = frozenset({
    "Person", "Place", "Event", "Concept",
    "Preference", "Goal", "Artifact", "Constraint",
})

GRAPH_EDGE_TYPES = frozenset({
    "KNOWS", "WORKS_AT", "LIVES_IN", "PARTICIPATED_IN",
    "LIKES", "DISLIKES", "WANTS", "INTERESTED_IN",
    "HAPPENED_AT", "RELATED_TO", "IS_FRIEND_OF",
    "IS_FAMILY_OF", "IS_COLLEAGUE_OF", "HAS_GOAL",
})

# Пороговые значения confidence
CONFIDENCE_AUTO_ACTIVE = 0.80    # выше — автоматически сохраняем
CONFIDENCE_CANDIDATE   = 0.55    # выше — создаём как candidate
CONFIDENCE_DISCARD     = 0.54    # ниже — игнорируем

# Важность по умолчанию для типов узлов
DEFAULT_IMPORTANCE: dict[str, float] = {
    "Person":     0.85,
    "Place":      0.65,
    "Event":      0.70,
    "Concept":    0.50,
    "Preference": 0.60,
    "Goal":       0.80,
    "Artifact":   0.45,
    "Constraint": 0.70,
}

GRAPH_MIGRATION_SQL = """
-- (полный DDL из раздела "Схема данных" выше)
"""
```

---

### `apps/backend/app/memory/graph/store.py`

```python
class GraphMemoryStore:
    """CRUD и запросы к граф-таблицам SQLite."""

    def __init__(self, db_path: str) -> None: ...

    # --- Сущности (узлы) ---
    def upsert_entity(
        self,
        display_name: str,
        node_type: str,
        properties: dict = {},
        importance: float | None = None,
        aliases: list[str] = [],
    ) -> str:
        """
        Создаёт или обновляет узел. Нормализует имя.
        Возвращает node_id. Идемпотентен.
        """

    def get_entity_by_name(self, name: str) -> dict | None:
        """FTS5 + точный поиск по canonical_name."""

    def find_entities(
        self,
        query: str,
        node_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Гибридный поиск: FTS5 + fuzzy fallback."""

    # --- Отношения (рёбра) ---
    def upsert_relation(
        self,
        source_id: str,
        rel_type: str,
        target_id: str,
        *,
        confidence: float = 0.7,
        episode_id: str | None = None,
        source_msg_id: str | None = None,
        properties: dict = {},
    ) -> str:
        """
        Создаёт или обновляет ребро.
        Если существует активное ребро того же типа — возвращает его id.
        При конфликте (другое значение) — инвалидирует старое, создаёт новое.
        """

    def invalidate_edge(self, edge_id: str) -> None:
        """Устанавливает valid_until = now на ребро (факт устарел)."""

    # --- Граф-запросы ---
    def get_neighborhood(
        self,
        entity_id: str,
        hops: int = 2,
        only_active: bool = True,
    ) -> dict:
        """
        Рекурсивный SQL WITH RECURSIVE (CTE) для N-hop traversal.
        Возвращает: {"nodes": [...], "edges": [...]}
        """

    def get_entity_relations(
        self,
        entity_id: str,
        rel_type: str | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        """Все рёбра для сущности (входящие + исходящие)."""

    def temporal_query(
        self,
        entity_id: str,
        at_time: str,  # ISO 8601
    ) -> list[dict]:
        """
        Рёбра, активные в конкретный момент времени:
        WHERE valid_from <= at_time AND (valid_until IS NULL OR valid_until > at_time)
        """

    # --- Retrieval ---
    def search_for_context(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        """
        Поиск сущностей для граф-контекста.
        FTS5 по именам → expand до neighbourhood → rank по importance.
        """
```

---

### `apps/backend/app/memory/nlp/natasha_ner.py`

```python
"""
Tier 1 NER: быстрый детерминированный Russian NER через natasha.
Не требует GPU. Latency < 10ms.
"""
from dataclasses import dataclass

@dataclass
class NerSpan:
    text: str
    type: str          # "PER" | "LOC" | "ORG"
    start: int
    stop: int


class NatashaExtractor:
    """Singleton: инициализируется один раз при старте backend."""

    _instance: "NatashaExtractor | None" = None

    def __init__(self) -> None:
        # lazy import для скорости старта
        from natasha import (
            Segmenter, MorphVocab, NewsEmbedding,
            NewsNERTagger, Doc,
        )
        self._segmenter = Segmenter()
        self._morph_vocab = MorphVocab()
        self._emb = NewsEmbedding()
        self._ner_tagger = NewsNERTagger(self._emb)
        self._Doc = Doc

    @classmethod
    def get(cls) -> "NatashaExtractor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def extract(self, text: str) -> list[NerSpan]:
        """
        Возвращает список NerSpan.
        Пустой список → LLM не вызывать.
        """
        doc = self._Doc(text)
        doc.segment(self._segmenter)
        doc.tag_ner(self._ner_tagger)
        return [
            NerSpan(span.text, span.type, span.start, span.stop)
            for span in doc.spans
        ]
```

---

### `apps/backend/app/memory/graph/extractor.py`

```python
"""
GraphExtractor: трёхступенчатый пайплайн извлечения графа.
  Tier 1: Natasha NER (CPU, <10ms)
  Tier 2: spaCy (CPU, <50ms) — если включён
  Tier 3: Qwen2.5 via Ollama (GPU, ~3–8s)
"""
import asyncio
import json
from dataclasses import dataclass
from json_repair import repair_json

from apps.backend.app.memory.nlp.natasha_ner import NatashaExtractor, NerSpan
from apps.backend.app.memory.graph.schema import (
    CONFIDENCE_AUTO_ACTIVE, CONFIDENCE_CANDIDATE, CONFIDENCE_DISCARD,
)


@dataclass
class ExtractedEntity:
    text: str
    canonical: str      # нормализованное имя
    node_type: str      # Person, Place, Event, ...
    importance: float


@dataclass
class ExtractedRelation:
    subject: str        # canonical entity name
    rel_type: str       # KNOWS, LIKES, etc.
    obj: str            # canonical entity name
    confidence: float
    context: str        # краткая фраза-пояснение


@dataclass
class ExtractionResult:
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
    tier_used: int      # 1, 2, или 3
    skipped: bool       # True если Tier 1 не нашёл ничего


class GraphExtractor:

    # Минимальная длина текста для запуска Tier 3 (токены)
    MIN_TEXT_LEN_FOR_LLM = 30

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        model_name: str = "qwen2.5:7b",
        timeout_sec: float = 30.0,
        use_spacy: bool = True,
    ) -> None:
        self._ollama_url = ollama_base_url
        self._model = model_name
        self._timeout = timeout_sec
        self._use_spacy = use_spacy
        self._natasha = NatashaExtractor.get()
        self._spacy_nlp = None  # lazy load

    async def extract(self, text: str, episode_id: str) -> ExtractionResult:
        """Основной метод. Вызывать асинхронно из worker."""

        # --- TIER 1: Natasha NER (всегда) ---
        spans = self._natasha.extract(text)
        if not spans or len(text) < self.MIN_TEXT_LEN_FOR_LLM:
            return ExtractionResult([], [], tier_used=1, skipped=True)

        # --- TIER 2: spaCy (опционально, если включён) ---
        if self._use_spacy:
            enriched_text = await self._enrich_with_spacy(text)
        else:
            enriched_text = text

        # --- TIER 3: LLM через Ollama ---
        try:
            entities = await self._llm_extract_entities(enriched_text)
            relations = await self._llm_extract_relations(enriched_text, entities)
            return ExtractionResult(entities, relations, tier_used=3, skipped=False)
        except OllamaUnavailableError:
            # Деградация: возвращаем только то, что нашла Natasha
            entities = self._spans_to_entities(spans)
            return ExtractionResult(entities, [], tier_used=1, skipped=False)

    async def _llm_extract_entities(self, text: str) -> list[ExtractedEntity]:
        """Pass 1: извлечение сущностей через LLM."""
        prompt = self._build_entity_prompt(text)
        raw = await self._ollama_chat(prompt, schema=ENTITY_JSON_SCHEMA)
        return self._parse_entities(raw)

    async def _llm_extract_relations(
        self, text: str, entities: list[ExtractedEntity]
    ) -> list[ExtractedRelation]:
        """Pass 2: извлечение отношений только между найденными сущностями."""
        if len(entities) < 1:
            return []
        prompt = self._build_relation_prompt(text, entities)
        raw = await self._ollama_chat(prompt, schema=RELATION_JSON_SCHEMA)
        return self._parse_relations(raw, entities)

    async def _ollama_chat(self, prompt: str, schema: dict) -> str:
        """
        Вызов Ollama API с принудительным JSON schema (constrained generation).
        POST /api/chat с format=schema.
        Raises OllamaUnavailableError при недоступности.
        """
        import httpx
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "format": schema,      # Ollama constrained generation
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 1024},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(
                    f"{self._ollama_url}/api/chat", json=payload
                )
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                raise OllamaUnavailableError(str(e)) from e

    def _parse_entities(self, raw: str) -> list[ExtractedEntity]:
        data = json.loads(repair_json(raw))
        result = []
        for item in data.get("entities", []):
            node_type = item.get("type", "Concept")
            if node_type not in VALID_NODE_TYPES:
                continue
            importance = float(item.get("importance", 0.5))
            if importance < 0.3:   # отсеиваем неважное
                continue
            result.append(ExtractedEntity(
                text=item["text"],
                canonical=self._canonicalize(item.get("canonical", item["text"])),
                node_type=node_type,
                importance=importance,
            ))
        return result

    def _parse_relations(
        self, raw: str, entities: list[ExtractedEntity]
    ) -> list[ExtractedRelation]:
        data = json.loads(repair_json(raw))
        known_canonicals = {e.canonical for e in entities} | {"user"}
        result = []
        for item in data.get("relations", []):
            confidence = float(item.get("confidence", 0.5))
            if confidence < CONFIDENCE_DISCARD:
                continue
            rel_type = item.get("relation", "").upper()
            if rel_type not in VALID_EDGE_TYPES:
                continue
            obj = self._canonicalize(item.get("object", ""))
            if obj not in known_canonicals:
                continue
            result.append(ExtractedRelation(
                subject=self._canonicalize(item.get("subject", "user")),
                rel_type=rel_type,
                obj=obj,
                confidence=confidence,
                context=item.get("context", "")[:200],
            ))
        return result

    @staticmethod
    def _canonicalize(name: str) -> str:
        """Нормализация: нижний регистр, ё→е, strip."""
        return name.strip().lower().replace("ё", "е")

    def _spans_to_entities(self, spans: list[NerSpan]) -> list[ExtractedEntity]:
        """Fallback: Natasha spans → ExtractedEntity без LLM."""
        type_map = {"PER": "Person", "LOC": "Place", "ORG": "Concept"}
        return [
            ExtractedEntity(
                text=s.text,
                canonical=self._canonicalize(s.text),
                node_type=type_map.get(s.type, "Concept"),
                importance=0.6,
            )
            for s in spans
        ]

    def _build_entity_prompt(self, text: str) -> str:
        return f"""{ENTITY_SYSTEM_PROMPT}

Текст разговора:
\"\"\"{text}\"\"\"

JSON:"""

    def _build_relation_prompt(
        self, text: str, entities: list[ExtractedEntity]
    ) -> str:
        entity_list = ", ".join(f'"{e.canonical}"' for e in entities)
        return f"""{RELATION_SYSTEM_PROMPT}

Найденные сущности: [{entity_list}]

Текст разговора:
\"\"\"{text}\"\"\"

JSON:"""


class OllamaUnavailableError(RuntimeError):
    """Ollama недоступна или таймаут."""
```

---

### `apps/backend/app/memory/graph/deduplicator.py`

```python
"""
EntityDeduplicator: нечёткое сопоставление имён перед записью в граф.
Предотвращает дублирование: "Иван" / "Ваня" / "ivan" → один узел.
"""
from rapidfuzz import fuzz, process


class EntityDeduplicator:

    SIMILARITY_THRESHOLD = 85  # % для Levenshtein

    def __init__(self, store: "GraphMemoryStore") -> None:
        self._store = store

    def find_or_suggest(
        self,
        canonical_name: str,
        node_type: str,
    ) -> str | None:
        """
        Ищет существующую сущность, похожую на canonical_name.
        Возвращает node_id если найдено совпадение, иначе None.

        Алгоритм:
        1. Точное совпадение canonical_name → сразу возвращаем
        2. FTS5 поиск по похожим именам
        3. rapidfuzz.fuzz.ratio > SIMILARITY_THRESHOLD → совпадение
        """
        # Шаг 1: точное совпадение
        exact = self._store.get_entity_by_name(canonical_name)
        if exact:
            return exact["id"]

        # Шаг 2: FTS5 кандидаты
        candidates = self._store.find_entities(canonical_name, node_type=node_type, limit=10)
        if not candidates:
            return None

        # Шаг 3: fuzzy matching
        candidate_names = [c["canonical_name"] for c in candidates]
        best = process.extractOne(
            canonical_name,
            candidate_names,
            scorer=fuzz.ratio,
            score_cutoff=self.SIMILARITY_THRESHOLD,
        )
        if best is None:
            return None

        matched_name, _score, idx = best
        return candidates[idx]["id"]

    def canonicalize(self, name: str) -> str:
        """
        Канонизация имени:
        - strip whitespace
        - нижний регистр
        - ё → е
        - двойные пробелы → один
        """
        return " ".join(name.strip().lower().replace("ё", "е").split())
```

---

### `apps/backend/app/memory/graph/worker.py`

```python
"""
GraphExtractorWorker: asyncio background worker.
Читает из очереди завершённых эпизодов, запускает extraction pipeline.
НЕ блокирует основной event loop.
"""
import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractionJob:
    episode_id: str
    text: str          # суммаризованный или полный текст эпизода
    source_msg_id: str | None = None


class GraphExtractorWorker:

    def __init__(
        self,
        extractor: "GraphExtractor",
        store: "GraphMemoryStore",
        deduplicator: "EntityDeduplicator",
        *,
        max_queue_size: int = 100,
        enabled: bool = True,
    ) -> None:
        self._extractor = extractor
        self._store = store
        self._deduplicator = deduplicator
        self._queue: asyncio.Queue[ExtractionJob] = asyncio.Queue(maxsize=max_queue_size)
        self._enabled = enabled
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Запуск фоновой задачи. Вызывать при старте приложения."""
        if self._enabled:
            self._task = asyncio.create_task(self._run(), name="graph-extractor")

    def stop(self) -> None:
        """Остановка. Вызывать при shutdown."""
        if self._task:
            self._task.cancel()

    async def enqueue(self, job: ExtractionJob) -> None:
        """
        Добавить эпизод в очередь на обработку.
        Если очередь полна — логируем и пропускаем (не блокируем).
        """
        if not self._enabled:
            return
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            logger.warning("graph_worker: queue full, skipping episode %s", job.episode_id)

    async def _run(self) -> None:
        """Основной цикл: обрабатываем по одному job."""
        logger.info("graph_worker: started")
        while True:
            try:
                job = await self._queue.get()
                await self._process(job)
                self._queue.task_done()
            except asyncio.CancelledError:
                logger.info("graph_worker: stopped")
                break
            except Exception:
                logger.exception("graph_worker: unhandled error in job %s", job.episode_id if job else "?")

    async def _process(self, job: ExtractionJob) -> None:
        """
        Pipeline для одного эпизода:
        1. Запуск extraction
        2. Deduplication + upsert узлов
        3. Upsert рёбер
        4. Отметить episode как graph_processed
        """
        result = await self._extractor.extract(job.text, job.episode_id)
        if result.skipped:
            self._store.mark_episode_processed(job.episode_id)
            return

        # Upsert сущностей
        node_ids: dict[str, str] = {}  # canonical → node_id
        for entity in result.entities:
            existing_id = self._deduplicator.find_or_suggest(
                entity.canonical, entity.node_type
            )
            if existing_id:
                node_id = existing_id
                # Обновляем важность если новая выше
                self._store.maybe_update_importance(node_id, entity.importance)
            else:
                node_id = self._store.upsert_entity(
                    display_name=entity.text,
                    node_type=entity.node_type,
                    importance=entity.importance,
                )
            node_ids[entity.canonical] = node_id

        # Добавляем "user" как особый узел (источник большинства рёбер)
        user_id = self._store.get_or_create_user_node()

        # Upsert отношений
        for rel in result.relations:
            src_id = user_id if rel.subject == "user" else node_ids.get(rel.subject)
            tgt_id = node_ids.get(rel.obj)
            if src_id and tgt_id:
                self._store.upsert_relation(
                    source_id=src_id,
                    rel_type=rel.rel_type,
                    target_id=tgt_id,
                    confidence=rel.confidence,
                    episode_id=job.episode_id,
                    source_msg_id=job.source_msg_id,
                    properties={"context": rel.context},
                )

        self._store.mark_episode_processed(job.episode_id)
        logger.debug(
            "graph_worker: episode %s → %d entities, %d relations",
            job.episode_id, len(result.entities), len(result.relations),
        )
```

---

### `apps/backend/app/memory/graph/retriever.py`

```python
"""
GraphRetriever: форматирует релевантный контекст из графа
для вставки в System Prompt как [GRAPH_CONTEXT] блок.
"""

MAX_CONTEXT_ENTITIES = 8    # максимум сущностей в блоке
MAX_CONTEXT_RELATIONS = 15  # максимум отношений


class GraphRetriever:

    def __init__(self, store: "GraphMemoryStore") -> None:
        self._store = store

    def get_context_block(self, query: str) -> str | None:
        """
        Ищет релевантные сущности и их связи.
        Форматирует в текстовый блок для System Prompt.
        Возвращает None если граф пустой или нерелевантен.
        """
        entities = self._store.search_for_context(query, limit=MAX_CONTEXT_ENTITIES)
        if not entities:
            return None

        lines: list[str] = ["[GRAPH_CONTEXT]"]
        for entity in entities:
            relations = self._store.get_entity_relations(entity["id"], active_only=True)
            entity_line = f"• {entity['display_name']} ({entity['type']})"
            rel_parts = []
            for rel in relations[:5]:  # max 5 связей на сущность
                other = self._store.get_entity_by_id(
                    rel["target_id"] if rel["source_id"] == entity["id"] else rel["source_id"]
                )
                if other:
                    rel_parts.append(f"{rel['rel_type']} {other['display_name']}")
            if rel_parts:
                entity_line += ": " + ", ".join(rel_parts)
            lines.append(entity_line)
        lines.append("[/GRAPH_CONTEXT]")

        return "\n".join(lines)

    def format_entity_summary(self, entity_id: str) -> str:
        """
        Подробное текстовое описание одной сущности со всеми связями.
        Используется в Memory Center UI.
        """
        entity = self._store.get_entity_by_id(entity_id)
        if not entity:
            return ""
        relations = self._store.get_entity_relations(entity_id)
        # ... форматирование
```

---

## Изменения в существующих файлах

### `apps/backend/app/memory/service.py`

Добавить:
1. **Feature flag** `graph_memory_enabled: bool` в `__init__`
2. **`GraphRetriever`** как опциональный атрибут
3. **Метод `retrieve_with_graph(query)`** — объединяет FTS и граф-контекст
4. **Вызов `graph_worker.enqueue()`** после `extract_from_message()` при `graph_memory_enabled`

```python
# Добавить в __init__:
self._graph_enabled = graph_memory_enabled and graph_retriever is not None
self._graph_retriever: GraphRetriever | None = graph_retriever

# Добавить метод:
def get_graph_context(self, query: str) -> str | None:
    if not self._graph_enabled or self.incognito:
        return None
    return self._graph_retriever.get_context_block(query)
```

---

### `apps/backend/app/storage/timeline.py`

SQL-миграция: добавить колонку `graph_processed INTEGER NOT NULL DEFAULT 0` в таблицу `episodes`.

Добавить методы:
- `mark_episode_graph_processed(episode_id: str) -> None`
- `get_unprocessed_episodes(limit: int = 50) -> list[dict]` (для будущего retroactive, не в V0.6)
```bash
# Windows:
winget install Ollama.Ollama
# После установки:
ollama pull qwen2.5:7b
```

---

## Конфигурация (runtime settings)

Добавить в `RuntimeSettings` / `.env.example`:

```python
# Graph Memory
GRAPH_MEMORY_ENABLED: bool = True
OLLAMA_BASE_URL: str = "http://localhost:11434"
GRAPH_LLM_MODEL: str = "qwen2.5:7b"      # или qwen2.5:3b если мало VRAM
GRAPH_LLM_TIMEOUT: float = 30.0
GRAPH_USE_SPACY: bool = True
GRAPH_MIN_CONFIDENCE: float = 0.55
GRAPH_WORKER_QUEUE_SIZE: int = 50
```

---

## Интеграционная диаграмма

```
Пользователь пишет сообщение
        │
        ▼
[MemoryService.extract_from_message()]   ← существующий код
        │
        ├──► Regex extraction (V0.5 — без изменений)
        │
        └──► [if graph_memory_enabled] GraphExtractorWorker.enqueue(job)
                        │            (асинхронно, не блокирует ответ)
                        ▼
              [GraphExtractorWorker._process()]
                        │
                        ├── NatashaExtractor.extract()     [Tier 1, CPU]
                        │   └── if empty → СТОП
                        │
                        ├── spaCy enrichment               [Tier 2, CPU]
                        │
                        └── GraphExtractor._llm_extract_*() [Tier 3, GPU]
                                    │
                                    ├── Ollama POST /api/chat (qwen2.5:7b)
                                    │   Pass 1: entities JSON
                                    │   Pass 2: relations JSON
                                    │
                                    └── EntityDeduplicator.find_or_suggest()
                                                │
                                                └── GraphMemoryStore.upsert_*()
                                                        │
                                                        └── SQLite: graph_nodes + graph_edges


LLM формирует ответ
        │
        ▼
[ContextManager.build_system_prompt()]
        │
        ├── ... существующие блоки ...
        │
        └── [if graph_memory_enabled] GraphRetriever.get_context_block(query)
                │
                └── GraphMemoryStore.search_for_context()
                        │
                        └── FTS5 → SQL neighbourhood → [GRAPH_CONTEXT] текстовый блок
```

---

## Roadmap — фазы выполнения

### Фаза 0: Подготовка окружения (1–2 дня)
- [ ] Установить Ollama (`winget install Ollama.Ollama`)
- [ ] `ollama pull qwen2.5:7b` (скачивает ~4.4 GB)
- [ ] Тест Ollama structured output: `curl http://localhost:11434/api/chat` с JSON schema
- [ ] Установить `natasha`, `spacy`, `ru_core_news_lg`
- [ ] Написать изолированный тест NER: 10 русских диалогов → проверить Natasha output
- [ ] Написать изолированный тест extraction: `qwen2.5:7b` → JSON по промпту из плана
- [ ] Зафиксировать оба промпта после тестирования (возможна итерация)

### Фаза 1: SQLite Graph Store (3–4 дня)
- [ ] `graph/schema.py` — константы, DDL строки
- [ ] Миграция `timeline.py`: добавить `graph_processed` в episodes + методы
- [ ] Миграция SQLite: новые таблицы `graph_nodes`, `graph_edges`, `graph_nodes_fts`
- [ ] `graph/store.py` — полная реализация всех методов:
  - [ ] `upsert_entity` + `get_entity_by_name` + `find_entities`
  - [ ] `upsert_relation` + `invalidate_edge`
  - [ ] `get_neighborhood` (рекурсивный CTE, hops=2)
  - [ ] `temporal_query`
  - [ ] `search_for_context`
  - [ ] `mark_episode_processed`
- [ ] Unit-тесты `test_graph_store.py`:
  - [ ] upsert идемпотентен
  - [ ] temporal query (valid_from/until)
  - [ ] neighbourhood CTE работает корректно
  - [ ] conflict resolution (старое ребро инвалидируется)

### Фаза 2: NLP & Extraction Pipeline (4–5 дней)
- [ ] `memory/nlp/natasha_ner.py` — Singleton NatashaExtractor
- [ ] `graph/deduplicator.py` — EntityDeduplicator (rapidfuzz)
- [ ] `graph/extractor.py` — GraphExtractor:
  - [ ] `_ollama_chat` с timeout и OllamaUnavailableError
  - [ ] `_llm_extract_entities` + `_parse_entities`
  - [ ] `_llm_extract_relations` + `_parse_relations`
  - [ ] Fallback на Natasha-only при недоступности Ollama
  - [ ] json_repair интеграция
- [ ] `graph/worker.py` — GraphExtractorWorker:
  - [ ] asyncio.Queue с max_queue_size
  - [ ] start() / stop() lifecycle
  - [ ] enqueue() без блокировки
  - [ ] _process() pipeline
- [ ] Unit-тесты `test_graph_extractor.py` (mock Ollama):
  - [ ] Успешный extraction
  - [ ] Ollama таймаут → fallback на Natasha
  - [ ] Невалидный JSON → json_repair
  - [ ] Низкий confidence → отбрасывается

### Фаза 3: Retriever & Интеграция (3–4 дня)
- [ ] `graph/retriever.py` — GraphRetriever:
  - [ ] `get_context_block` (FTS → neighbourhood → текстовый блок)
  - [ ] Токен-бюджет: блок пропускается если System Prompt слишком большой
- [ ] `memory/service.py` — добавить:
  - [ ] `graph_memory_enabled` feature flag
  - [ ] `get_graph_context(query)` делегирует в GraphRetriever
  - [ ] Вызов `worker.enqueue()` в `extract_from_message()`
- [ ] Context Manager — вставка `[GRAPH_CONTEXT]` в System Prompt
- [ ] `main.py` (или DI-контейнер) — инициализация и lifecycle worker'а
- [ ] Integration test: сообщение → extraction → граф → retrieval → System Prompt

### Фаза 4: API & Memory Center (2–3 дня)
- [ ] `GET /api/memory/graph/entities` — список всех узлов с пагинацией
- [ ] `GET /api/memory/graph/entity/{id}` — детали + все связи
- [ ] `GET /api/memory/graph/search?q=...` — поиск по сущностям
- [ ] `DELETE /api/memory/graph/entity/{id}` — удаление узла + cascade рёбра
- [ ] `PATCH /api/memory/graph/entity/{id}` — редактирование display_name, properties
- [ ] `DELETE /api/memory/graph/edge/{id}` — удаление/инвалидация ребра
- [ ] `GET /api/memory/graph/export` — JSON dump всего графа (backup)
- [ ] Memory Center UI: базовый список сущностей с типами и связями

### Фаза 5: Стабилизация (2–3 дня)
- [ ] Evaluation corpus: 30 диалогов с ручной разметкой → precision/recall
- [ ] VRAM benchmark: Whisper active + Qwen2.5:7b extraction → профилирование
- [ ] Graceful degradation тест: выключить Ollama → Tier 1 fallback работает
- [ ] Stress test worker: 100 быстрых сообщений → очередь не переполняется
- [ ] Документация: схема БД, промпт-шаблоны, конфиг-переменные

**Общая оценка: ~14–17 дней**

---

## Открытые вопросы (для уточнения)

> [!NOTE]
> **Q1: Какая модель основного ассистента?**
> Если основная LLM тоже локальная (через Ollama/llama.cpp), нужна стратегия очерёдности загрузки в VRAM. Если облачная — никаких конфликтов нет.

> [!NOTE]
> **Q2: Формат текста для extraction worker'а**
> Что передавать в worker: (a) сырые сообщения эпизода, (b) готовый episode_summary, или (c) оба варианта? Summary компактнее, но может потерять детали. Рекомендация: summary если есть, иначе последние N сообщений эпизода.

> [!NOTE]
> **Q3: Видимость `[GRAPH_CONTEXT]` для пользователя**
> Блок идёт в System Prompt (невидим в UI). Если хочется — можно добавить диагностику в Memory Center, показывающую что сейчас инжектировано в промпт.

---

## Полезные источники

- `getzep/graphiti` — arXiv:2501.13956 (bi-temporal KG)
- `mem0ai/mem0` — conflict detection, supersession
- `natasha-nlp/natasha` — Russian NER CPU
- `HKUDS/LightRAG` — graph+vector retrieval
- NEREL / RURED — Russian NLP benchmarks
- Ollama structured outputs: https://ollama.com/blog/structured-outputs
