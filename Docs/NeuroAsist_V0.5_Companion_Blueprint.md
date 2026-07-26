# NeuroAsist V0.5 — Continuous Companion Blueprint

> Historical architecture document from before the Iris rebrand. Iris is the current public name; the NeuroAsist references below preserve the original version, repository, and runtime paths.

**Полное название:** NeuroAsist V0.5 — Live Desktop Companion, Episodic Context & Long-Term Memory  
**Базовая версия:** `bad1and/NeuroAsist`, ветка/тег `v0.4.1`  
**Дата пересмотра:** 14 июля 2026  
**Основной исполнитель:** Codex / другой coding-agent  
**Статус:** новый основной план V0.5. Он заменяет предыдущую версию с отдельными чатами и старый roadmap Dev Agent.

---

# 0. Главное изменение концепции

NeuroAsist — не аналог ChatGPT с отдельными чатами.

Это **один постоянный персонаж**, который:

- живёт на рабочем столе;
- остаётся одной и той же личностью;
- может в любой момент услышать пользователя;
- поддерживает непрерывное общение;
- помнит прошлые разговоры;
- эмоционально реагирует;
- сохраняет ощущение общей истории;
- может работать часами как live-персонаж;
- не начинает жизнь заново после каждого перезапуска.

Целевая пользовательская модель:

```text
Пользователь запускает компьютер
  → Нейро появляется на рабочем столе
  → сидит в углу экрана
  → реагирует на обращение
  → разговаривает
  → запоминает важное
  → после паузы остаётся в idle-режиме
  → через день помнит контекст отношений
```

Поэтому в V0.5 **не делается система отдельных пользовательских чатов**.

Вместо неё создаётся:

```text
единая временная линия общения
  + автоматические разговорные эпизоды
  + краткие summaries
  + долгосрочная память
  + динамический Context Manager
```

Пользователь видит одного персонажа и одну общую историю. Эпизоды являются внутренней технической структурой и не превращают интерфейс в мессенджер.

---

# 1. Решение в одном абзаце

V0.5 должна превратить текущий голосовой прототип в **постоянного локального desktop-компаньона**.

Рекомендуемая архитектура:

```text
┌──────────────────────────────────────────────────────────────┐
│ NeuroAsist Desktop — Tauri 2 + существующий React UI         │
│ Tray · настройки · журнал · память · запуск компонентов       │
└────────────────────────┬─────────────────────────────────────┘
                         │ localhost HTTP/WebSocket + auth
┌────────────────────────▼─────────────────────────────────────┐
│ Neuro Core — Python/FastAPI managed sidecar                  │
│ Character · Timeline · Episodes · Context · Memory           │
│ STT · VAD · TTS · Events · Settings · Avatar orchestration   │
└───────────────┬────────────────────────────────┬─────────────┘
                │ Avatar Protocol v3             │ providers
┌───────────────▼──────────────────┐   ┌─────────▼─────────────┐
│ Neuro Avatar — Unity/VRM        │   │ STT/TTS/LLM/Embeddings│
│ transparent desktop companion   │   │ local or cloud        │
└──────────────────────────────────┘   └───────────────────────┘
```

Ключевые решения:

- React сохраняется.
- Python/FastAPI сохраняется.
- Unity сохраняется как отдельный avatar renderer.
- Tauri становится desktop-оболочкой.
- Один пользовательский timeline заменяет список чатов.
- История автоматически делится на внутренние episodes.
- Старые episodes сжимаются в summaries.
- В prompt попадает только динамически собранный релевантный контекст.
- Долгосрочная память отделяется от полной истории.
- Dev Agent в V0.5 не реализуется.

---

# 2. Что означает live

Под live понимается не модерация стрима и не обязательная интеграция с Twitch/YouTube.

Live — это поведение персонажа:

- он постоянно доступен;
- его состояние существует между репликами;
- он может слушать по VAD;
- пользователь может заговорить в любой момент;
- персонажа можно перебить;
- он не исчезает после ответа;
- idle-анимации продолжаются;
- эмоция плавно возвращается к baseline;
- приложение может работать длительное время;
- общение воспринимается как одна непрерывная жизнь.

В V0.5 не требуются:

- ban words;
- moderation dashboard;
- donation alerts;
- Twitch/YouTube chat ingestion;
- несколько зрителей;
- streamer safety controls.

Это может появиться позже отдельным Stream Integration Layer.

---

# 3. Фактическое состояние V0.4.1

Уже реализованы:

- FastAPI backend;
- React 19 + TypeScript + Vite;
- SQLite history;
- Character Agent;
- OpenAI-compatible LLM provider;
- `faster-whisper`;
- Silero TTS;
- push-to-talk;
- live text streaming;
- live TTS segments;
- runtime events;
- Unity VRM client;
- uLipSync;
- эмоции и gestures;
- Avatar Protocol v1/v2;
- heartbeat и reconnect;
- latency telemetry;
- Unity motion framework;
- full-WAV и segment playback;
- test endpoints;
- базовые smoke-критерии.

Проект уже не находится на этапе «собрать первый голосовой цикл». Задача V0.5 — объединить существующие части в устойчивую непрерывную систему.

## 3.1. Проблема текущей истории

Сейчас backend:

```text
берёт последние N сообщений по session_id
  → кладёт их в prompt
  → получает ответ
  → сохраняет user и assistant message
```

Для персонажа, который живёт неделями и месяцами, этого недостаточно:

- история растёт бесконечно;
- в prompt помещается только хвост;
- старые важные события теряются;
- случайные старые сообщения не должны постоянно попадать в контекст;
- нет автоматического разделения разговоров;
- нет summaries;
- нет temporal context;
- нет долгосрочной памяти;
- нет понимания «сегодня», «вчера», «в прошлый раз».

## 3.2. Что делать с `default` session

Фиксированный `default` можно временно сохранить как compatibility identifier, но не как архитектуру V0.5.

Целевая структура:

```text
relationship_id / companion_id
  └── одна общая timeline
        ├── episode 1
        ├── episode 2
        ├── episode 3
        └── current active episode
```

Не делать:

```text
user manually creates chat
user switches chat
each chat has separate personality
```

Делать:

```text
system automatically groups messages into episodes
user always communicates with the same character
```

---

# 4. Цель V0.5

После завершения V0.5 пользователь должен:

1. Установить одно приложение.
2. Запустить его одним ярлыком.
3. Увидеть 3D-аватара на рабочем столе.
4. Заговорить с ним без открытия отдельной страницы.
5. При необходимости открыть компактную текстовую панель.
6. Перебить его во время ответа.
7. Продолжить разговор после паузы.
8. Закрыть приложение и продолжить позже.
9. Спросить о прошлом разговоре.
10. Посмотреть, что персонаж помнит.
11. Исправить или удалить память.
12. Включить режим «не запоминать».
13. Очистить недавнюю историю отдельно от долгосрочной памяти.
14. Работать с приложением часами без деградации.
15. Получать понятную диагностику при сбоях STT, TTS, Unity и backend.

---

# 5. Что не входит в V0.5

Не реализовывать:

- отдельные пользовательские чаты;
- Dev Agent;
- filesystem tools;
- shell commands;
- screen understanding;
- управление мышью и клавиатурой;
- браузерную автоматизацию;
- Twitch/YouTube ingestion;
- moderation/banned words;
- multi-user mode;
- SaaS;
- cloud memory sync;
- knowledge graph;
- autonomous background goals;
- production voice cloning;
- сложный multi-agent orchestration;
- переписывание Unity avatar на Three.js;
- Kubernetes, Redis, Celery и микросервисы.

---

# 6. Основные принципы

1. **Один персонаж — одна идентичность.**
2. **Полная история не равна prompt.**
3. **Summary не равен memory.**
4. **Episode не равен chat.**
5. **Сначала FTS и правила, потом vectors.**
6. **LLM предлагает memory candidate, приложение решает.**
7. **Любой поток STT → LLM → TTS → Unity можно отменить.**
8. **Только один компонент владеет воспроизведением аудио.**
9. **Фоновая summarization или memory extraction не блокирует ответ.**
10. **Удалённые данные не должны продолжать влиять на контекст.**

---

# 7. Целевая структура репозитория

```text
NeuroAsist/
├─ apps/
│  ├─ backend/
│  │  └─ app/
│  │     ├─ agents/character/
│  │     ├─ timeline/
│  │     ├─ episodes/
│  │     ├─ context/
│  │     ├─ memory/
│  │     ├─ voice/
│  │     ├─ avatar/
│  │     ├─ llm/
│  │     ├─ runtime/
│  │     ├─ storage/
│  │     ├─ events/
│  │     └─ api/
│  ├─ web/
│  └─ desktop/src-tauri/
├─ packages/
│  ├─ protocol/
│  │  ├─ schemas/
│  │  ├─ generated-python/
│  │  ├─ generated-typescript/
│  │  └─ generated-csharp/
│  └─ ui/
├─ Docs/
│  ├─ neuroasist_v0.5_continuous_companion_blueprint.md
│  ├─ adr/
│  ├─ memory-evaluation.md
│  ├─ context-evaluation.md
│  ├─ packaging-windows.md
│  └─ release-checklist-v0.5.md
├─ tests/
│  ├─ timeline/
│  ├─ episodes/
│  ├─ context_eval/
│  ├─ memory_eval/
│  ├─ integration/
│  └─ e2e/
└─ scripts/
```

---

# 8. Unity source ownership

Unity-проект должен быть доступен Codex и CI.

Рекомендуется отдельный репозиторий:

```text
bad1and/NeuroAsistAvatar
```

Основной repo хранит:

- pinned commit;
- protocol version;
- build manifest;
- expected build hash;
- compatibility table;
- build instructions.

Допустим git submodule, но абсолютные пути и Unity source только на одном ПК запрещены.


---

# 9. Модель единой временной линии

## 9.1. Основные сущности

```text
CompanionRelationship
ConversationTimeline
ConversationEpisode
ConversationMessage
EpisodeSummary
MemoryItem
CharacterState
```

## 9.2. CompanionRelationship

Для V0.5 пользователь один, персонаж один.

```sql
CREATE TABLE companion_relationships (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    first_interaction_at TEXT,
    last_interaction_at TEXT,
    total_interactions INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

Default:

```text
relationship_id = primary
character_id = neuro
user_id = local_user
```

Эта сущность нужна не для SaaS, а чтобы не строить всю систему вокруг строки `default`.

## 9.3. Timeline

Timeline — общая история отношений. В V0.5 для primary relationship существует одна timeline.

```sql
CREATE TABLE conversation_timelines (
    id TEXT PRIMARY KEY,
    relationship_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    current_episode_id TEXT,
    latest_message_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

## 9.4. Messages

```sql
CREATE TABLE conversation_messages (
    id TEXT PRIMARY KEY,
    timeline_id TEXT NOT NULL,
    episode_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,

    client_message_id TEXT,
    utterance_id TEXT,
    generation INTEGER,

    status TEXT NOT NULL,
    input_mode TEXT NOT NULL,
    language TEXT,

    created_at TEXT NOT NULL,
    completed_at TEXT,
    cancelled_at TEXT,

    corrected_content TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

`role`:

```text
user
assistant
system_event
```

`status`:

```text
pending
accepted
streaming
completed
cancelled
interrupted
failed
```

`input_mode`:

```text
voice
text
system
```

Unique:

```text
(timeline_id, client_message_id)
```

## 9.5. Append-only правило

Completed messages не редактировать физически без следа.

При исправлении transcription:

- сохранить исходный текст;
- записать correction;
- использовать `corrected_content`;
- оставить audit;
- пометить summaries и memories на перепроверку, если исправление важное.

---

# 10. Разговорные эпизоды

## 10.1. Определение

Episode — внутренний отрезок непрерывного общения:

```text
утренний разговор о проекте
короткое обсуждение еды
вечернее тестирование аватара
разговор после перезапуска приложения
```

Episode не является отдельной личностью и не требует ручного создания.

## 10.2. Схема

```sql
CREATE TABLE conversation_episodes (
    id TEXT PRIMARY KEY,
    timeline_id TEXT NOT NULL,

    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    ended_at TEXT,

    boundary_reason TEXT,
    title TEXT,

    message_count INTEGER NOT NULL DEFAULT 0,
    token_estimate INTEGER NOT NULL DEFAULT 0,

    summary_status TEXT NOT NULL DEFAULT 'none',
    summary_version INTEGER NOT NULL DEFAULT 0,

    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

`status`:

```text
active
closing
closed
summarizing
summarized
failed
```

`boundary_reason`:

```text
inactivity
application_restart
calendar_boundary
topic_shift
manual_reset
context_pressure
recovery
```

## 10.3. Baseline boundary detection

Не начинать с LLM-классификатора темы.

Episode закрывается при одном из условий:

1. Пауза больше threshold.
2. Новый календарный день и значительная пауза.
3. Корректное завершение приложения.
4. Recovery после crash.
5. Максимальный размер episode.
6. Пользователь явно просит сменить/закрыть текущий разговор.
7. Context Manager требует segmentation из-за token pressure.

Стартовые настройки:

```text
soft inactivity threshold = 20 минут
hard inactivity threshold = 60 минут
maximum episode messages = 120
maximum episode estimated tokens = 16000
```

Параметры должны быть configurable и проверены на реальном использовании.

## 10.4. Короткая и длинная пауза

Короткая пауза:

```text
пользователь отошёл на 5–10 минут
→ продолжить active episode
```

Длинная пауза:

```text
пользователь вернулся через несколько часов
→ закрыть старый episode
→ новый создать при первой реплике
```

Не создавать пустой episode на каждом запуске.

## 10.5. Topic shift

Semantic topic shift — только дополнительная функция после baseline.

Возможная логика:

```text
embedding текущей темы episode
+ embedding нескольких новых turns
→ устойчивый сильный shift
→ минимум N turns в старой теме
→ закрытие episode
```

Нельзя закрывать episode после одной случайной фразы.

## 10.6. Startup recovery

При старте:

- найти active episode;
- проверить последнюю активность;
- при короткой паузе продолжить;
- при длинной закрыть с `application_restart` или `recovery`;
- новый episode открыть только после реального сообщения.

---

# 11. Episode Summary

## 11.1. Назначение

Summary сохраняет контекст старого разговора без отправки всех сообщений модели.

Summary должен быть структурированным, а не красивым литературным пересказом.

## 11.2. Схема

```sql
CREATE TABLE episode_summaries (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    version INTEGER NOT NULL,

    summary_text TEXT NOT NULL,
    topics_json TEXT NOT NULL DEFAULT '[]',
    decisions_json TEXT NOT NULL DEFAULT '[]',
    open_loops_json TEXT NOT NULL DEFAULT '[]',
    emotional_context_json TEXT NOT NULL DEFAULT '{}',
    referenced_entities_json TEXT NOT NULL DEFAULT '[]',

    source_message_ids_json TEXT NOT NULL DEFAULT '[]',
    model_id TEXT,
    prompt_version TEXT NOT NULL,

    created_at TEXT NOT NULL,
    superseded_at TEXT
);
```

## 11.3. Пример

```json
{
  "summary": "Пользователь уточнил, что NeuroAsist должен быть постоянным live desktop-компаньоном, а не приложением с отдельными чатами.",
  "topics": [
    "continuous companion",
    "conversation episodes",
    "V0.5 planning"
  ],
  "decisions": [
    "Не реализовывать отдельные пользовательские чаты",
    "Использовать одну timeline и автоматические episodes"
  ],
  "open_loops": [
    "Переписать Blueprint V0.5",
    "Подобрать inactivity threshold"
  ],
  "emotional_context": {
    "user": "engaged",
    "character": "neutral"
  },
  "entities": [
    "NeuroAsist",
    "V0.5"
  ]
}
```

## 11.4. Когда строить summary

- при закрытии episode;
- при context pressure;
- по ручной команде compact;
- после исправления важных сообщений;
- при новой версии summarizer;
- после удаления исходных данных, если summary содержит их.

## 11.5. Rolling summary

Для длинного active episode:

```text
rolling summary
+ последние raw turns
```

Rolling summary нужен только для текущего контекста. Final summary создаётся при закрытии episode.

## 11.6. Ошибка summarization

Если LLM недоступна:

- episode всё равно закрывается;
- raw history остаётся;
- summary job получает `failed/retry`;
- новый разговор не блокируется.

---

# 12. Context Manager

## 12.1. Главная роль

`ContextManager` заменяет нынешнее «последние N сообщений».

Перед запросом он собирает:

```text
Character identity
+ behavior rules
+ current runtime state
+ stable user profile
+ relevant long-term memories
+ current episode rolling summary
+ relevant old episode summaries
+ recent raw turns
+ current user message
```

## 12.2. Интерфейс

```python
class BuiltContext(BaseModel):
    system_identity: str
    character_state: str
    stable_profile: list
    relevant_memories: list
    episode_context: list
    recent_messages: list
    token_estimate: int
    diagnostics: dict
```

## 12.3. Model-aware budget

Пример распределения:

```text
system/personality        800–1500 tokens
character runtime state   100–250
stable profile            300–600
retrieved memories        400–900
episode summaries         500–1200
recent raw history       1500–4000
current request            reserved
response budget            reserved
```

Размеры рассчитываются относительно context window выбранной модели.

## 12.4. Приоритеты при сжатии

Сначала убирать:

1. низкооценённые episodic memories;
2. старые нерелевантные summaries;
3. неважные raw turns;
4. второстепенные profile facts.

Нельзя автоматически убрать:

- identity;
- текущую user message;
- системные ограничения;
- user-confirmed critical preferences;
- текущие unresolved references.

## 12.5. Recent window

Recent window считается turns, а не отдельными строками.

Не разрывать user/assistant pair без необходимости.

## 12.6. Diagnostics

В development UI показывать:

- sections;
- token estimate;
- выбранные memory IDs;
- выбранные episode IDs;
- причины выбора;
- отброшенные элементы;
- compact reason.

---

# 13. История, Summary и Memory

## История

Полные сообщения. Нужна для просмотра, provenance, export, повторной summarization и debugging.

## Summary

Сжатое описание конкретного episode. Нужное для continuity.

## Memory

Отдельный устойчивый факт или важное событие.

Пример:

```text
История:
«Не делай нам отдельные чаты, Нейро должна жить на рабочем столе».

Summary:
«Архитектуру V0.5 изменили с chat application на continuous companion».

Memory:
«Пользователь хочет постоянного desktop-компаньона без отдельных чатов».
```

---

# 14. Архитектура памяти

Слои:

```text
Layer 0 — Raw Timeline
Layer 1 — Current Episode Working Context
Layer 2 — Episode Summaries
Layer 3 — Stable User Profile
Layer 4 — Episodic Long-Term Memory
Layer 5 — Character/Relationship State
```

## Stable Profile

- язык;
- стиль общения;
- устойчивые предпочтения;
- долгосрочные цели;
- интересы;
- recurring constraints;
- значимые имена и отношения.

## Episodic Memory

- важное решение;
- milestone;
- завершённая задача;
- значимый совместный момент;
- незакрытый вопрос.

## Relationship Memory

Можно хранить:

```text
first interaction date
interaction count
shared milestones
recurring jokes
last important event
```

Не строить скрытый психологический профиль.

## Character State

```text
mood baseline
current emotion
energy
last interaction time
active topic
speaking/listening state
```

Transient state имеет decay и не является вечной памятью.


---

# 15. Схема Memory

```sql
CREATE TABLE memory_items (
    id TEXT PRIMARY KEY,
    relationship_id TEXT NOT NULL,

    scope TEXT NOT NULL,
    kind TEXT NOT NULL,

    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value_text TEXT NOT NULL,
    canonical_text TEXT NOT NULL,

    importance REAL NOT NULL DEFAULT 0.5,
    confidence REAL NOT NULL DEFAULT 0.5,
    sensitivity TEXT NOT NULL DEFAULT 'normal',

    status TEXT NOT NULL DEFAULT 'active',
    user_locked INTEGER NOT NULL DEFAULT 0,

    valid_from TEXT,
    valid_to TEXT,
    expires_at TEXT,

    source_episode_id TEXT,
    source_message_ids_json TEXT NOT NULL DEFAULT '[]',
    extractor_version TEXT NOT NULL,

    supersedes_id TEXT,
    superseded_by_id TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_accessed_at TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,

    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

`scope`:

```text
user_profile
relationship
episode
character
```

`kind`:

```text
identity
preference
relationship
goal
constraint
skill
interest
episode
decision
correction
open_loop
shared_milestone
```

`status`:

```text
candidate
active
superseded
rejected
deleted
expired
```

---

# 16. Memory Audit

```sql
CREATE TABLE memory_audit (
    id TEXT PRIMARY KEY,
    memory_id TEXT,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    reason TEXT,
    source_message_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
```

`actor`:

```text
extractor
policy
user
system
migration
```

Действия:

```text
candidate_created
activated
edited
confirmed
rejected
superseded
deleted
restored
expired
retrieved
```

---

# 17. Memory Write Pipeline

```text
completed turn
  → candidate extraction
  → strict schema validation
  → evidence validation
  → sensitivity policy
  → deduplication
  → conflict resolution
  → candidate/active decision
  → audit
  → search index update
```

LLM возвращает только candidate:

```json
{
  "operation": "upsert",
  "scope": "user_profile",
  "kind": "preference",
  "subject": "user",
  "predicate": "preferred_assistant_mode",
  "value": "continuous desktop companion without separate chats",
  "confidence": 0.97,
  "importance": 0.9,
  "sensitivity": "normal",
  "evidence_message_ids": ["msg_..."]
}
```

`MemoryService`, а не LLM, применяет или отклоняет операцию.

## 17.1. Источник

Новый факт нельзя создавать только из assistant reply.

Допустимые источники:

- user message;
- explicit user correction;
- system event;
- user-confirmed candidate.

## 17.2. Режимы

```text
Off
Ask before saving
Automatic normal facts
```

Для чувствительных данных:

```text
Never
Ask
```

## 17.3. Ограничение writes

```text
max automatic candidates per turn = 3
```

Это предотвращает превращение памяти в свалку.

## 17.4. Deduplication

Результат:

```text
new
duplicate
update
conflict
ignore
```

Сравнивать:

- normalized subject/predicate;
- canonical text;
- exact entity match;
- FTS similarity;
- optional vector similarity.

## 17.5. Conflicts

Старую запись нельзя молча перезаписывать.

```text
old.status = superseded
old.superseded_by_id = new.id
new.supersedes_id = old.id
```

При сомнении:

```text
new.status = candidate
```

## 17.6. Forget/correct commands

До основного LLM добавить detector:

```text
запомни
не запоминай
забудь
это неверно
я больше не...
теперь я...
что ты помнишь
очисти память
```

LLM может извлечь объект, но операцию выполняет MemoryService.

---

# 18. Memory Retrieval

## 18.1. Pipeline

```text
current user message
  → query analysis
  → exact profile matches
  → current episode context
  → FTS5 memory search
  → FTS5 episode summary search
  → optional vector search
  → rank fusion
  → temporal filtering
  → conflict filtering
  → relevance threshold
  → token budget
  → rendered context
```

## 18.2. FTS-first

SQLite FTS5 — обязательный baseline для:

- memories;
- episode summaries;
- raw history search.

## 18.3. Vector adapter

```python
class VectorIndex(Protocol):
    async def upsert(self, item_id: str, text: str, namespace: str) -> None: ...
    async def delete(self, item_id: str, namespace: str) -> None: ...
    async def search(self, query: str, namespace: str, limit: int) -> list: ...
    async def rebuild(self, namespace: str) -> None: ...
```

Реализации:

```text
NullVectorIndex
SqliteVecIndex
```

Namespaces:

```text
memory
episode_summary
```

Требования:

- при ошибке vector extension работает FTS;
- canonical data хранится в обычных SQLite tables;
- index полностью rebuildable;
- model ID и dimension сохраняются;
- vectors разных моделей не смешиваются.

## 18.4. Fusion

Пример:

```text
score =
    0.32 semantic
  + 0.24 BM25
  + 0.16 entity
  + 0.10 temporal
  + 0.10 importance
  + 0.08 confidence
```

Формула конфигурируется и проверяется benchmark.

## 18.5. Temporal retrieval

Фразы:

```text
раньше
вчера
сегодня
в прошлый раз
когда мы...
до этого
потом
```

включают temporal strategy.

## 18.6. Abstention

Если данные не найдены:

- не выдумывать;
- не говорить «я помню» без source;
- честно сообщать о неуверенности.

---

# 19. Context Continuity

## 19.1. После короткой паузы

- продолжить active episode;
- сохранить тему;
- не делать повторное приветствие.

## 19.2. После долгой паузы

- закрыть старый episode;
- открыть новый при реплике;
- при необходимости добавить внутренний continuity context:

```text
Last relevant interaction:
Пользователь обсуждал переработку V0.5 под continuous companion.
```

Это не обязательно произносить.

## 19.3. На следующий день

Персонаж может учитывать:

- дату;
- время отсутствия;
- последний важный topic;
- open loops.

Не превращать это в механическую фразу о количестве часов.

## 19.4. Open Loops

Summary может хранить:

```text
переписать Blueprint
проверить Tauri
подобрать анимации
```

Это не task manager. Open loops нужны только для conversational continuity.

---

# 20. Timeline UI вместо Chat UI

## 20.1. Основной режим

Интерфейс не должен выглядеть как ChatGPT.

Целевой UX:

```text
avatar overlay
+ компактный voice indicator
+ optional mini input
+ tray controls
```

## 20.2. Companion Panel

- текущая реплика;
- последние сообщения;
- voice state;
- avatar state;
- поле ввода;
- microphone;
- stop;
- mute;
- memory shortcut;
- settings.

## 20.3. Journal

Отдельная вкладка:

```text
История / Journal
```

Показывает:

- периоды по датам;
- episodes;
- summaries;
- раскрытие полного диалога;
- поиск;
- export;
- удаление периода.

Пример:

```text
Сегодня, 14:20 — Планирование V0.5
Вчера вечером — Настройка аватара
12 июля — Голос и TTS
```

Titles генерируются автоматически.

## 20.4. Privacy controls

Для текущего разговора:

```text
Не запоминать этот разговор
Не создавать memories
Не сохранять raw audio
Удалить последние 10 минут
Закрыть текущий episode
```

---

# 21. Memory Center

Функции:

- search;
- filters;
- stable profile;
- relationship memories;
- episodes;
- decisions;
- open loops;
- candidate queue;
- active/superseded/deleted;
- source episode;
- source message;
- edit;
- pin;
- forget;
- restore;
- manual memory;
- export/import;
- clear;
- rebuild index.

## 21.1. Explainability

Для каждой memory:

```text
Почему запомнено
Когда создано
Из какого разговора
Когда использовалось
Почему попало в текущий context
```

## 21.2. Разные очистки

```text
Очистить последние сообщения
Удалить episode
Удалить summaries
Удалить extracted memories
Очистить profile memory
Очистить всё
Factory reset
```

Нельзя смешивать это одной кнопкой.

---

# 22. Character Architecture

Character Agent получает:

- identity;
- relationship context;
- current episode;
- recent messages;
- relevant memories;
- current emotion state;
- input mode;
- voice constraints;
- time since last interaction.

## 22.1. Persona config

```yaml
character:
  id: neuro
  display_name: "Нейро"
  gender: female
  language: ru
  relationship_style: close_friend

  response:
    default_length: short
    profanity: enabled
    sarcasm: 0.7
    warmth: 0.8

  voice:
    spoken_text_policy: conversational

  continuity:
    mention_old_context_only_when_relevant: true
    avoid_repeated_greetings: true
```

Не хранить номер версии продукта в persona prompt.

## 22.2. Relationship-aware behavior

Персонаж может:

- помнить решения;
- понимать recurring jokes;
- ссылаться на прошлое;
- не представляться при каждом запуске;
- не вести себя как новый бот.

Он не должен:

- притворяться, что помнит удалённые данные;
- выдумывать общую историю;
- слишком часто повторять memories;
- каждую фразу начинать с «я помню, что ты...».

---

# 23. Character Protocol v3

## 23.1. Единый контракт

```python
class CharacterTurn(BaseModel):
    reply: str
    intent: Intent
    affect: AffectCue
    gesture: GestureCue
    delivery: DeliveryCue
    continuity: ContinuityCue | None = None

class ContinuityCue(BaseModel):
    referenced_memory_ids: list[str] = []
    referenced_episode_ids: list[str] = []
    closes_open_loop_ids: list[str] = []
```

## 23.2. Affect

```python
class AffectCue(BaseModel):
    emotion: Emotion
    intensity: float
    valence: float
    arousal: float
```

Canonical emotions:

```text
neutral
happy
sad
angry
annoyed
smirk
thinking
surprised
embarrassed
concerned
```

## 23.3. Live events

```text
voice.turn.started
character.metadata
character.text.delta
character.text.completed
tts.segment
voice.turn.completed
```

Metadata передаётся отдельным frame, а не видимой строкой.

## 23.4. Schemas

Один JSON Schema:

```text
→ Pydantic
→ TypeScript
→ C#
```

CI проверяет generated artifacts.

## 23.5. Fallback

При invalid metadata:

- текст сохраняется;
- emotion = neutral/rule-based;
- gesture = auto;
- intent определяется локально;
- reply не теряется;
- пишется diagnostic event.


---

# 24. Character Runtime State

```sql
CREATE TABLE character_runtime_state (
    character_id TEXT PRIMARY KEY,
    mood_baseline TEXT NOT NULL,
    current_emotion TEXT NOT NULL,
    emotion_intensity REAL NOT NULL,
    energy REAL NOT NULL,
    active_topic TEXT,
    last_user_interaction_at TEXT,
    last_spoke_at TEXT,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

Transient state можно держать в RAM и периодически checkpoint-ить.

Не строить в V0.5 сложную симуляцию психики.

---

# 25. Emotion & Motion Engine

Разделить:

```text
face expression
body gesture
idle animation
head/gaze
lip sync
voice delivery
```

State:

```text
current emotion
target emotion
intensity
attack
minimum hold
release
source utterance
generation
```

Правила:

- плавные переходы;
- gesture priorities;
- old generation не сбрасывает новый;
- long idle не запускается во время speech;
- stop возвращает baseline;
- emotion не меняется на каждом TTS segment;
- одна metadata применяется ко всей utterance;
- face, body и gaze не конфликтуют.

Unity mapping хранить в config asset:

```json
{
  "happy": {
    "expression": "happy",
    "weight": 0.8,
    "motion_profile": "energetic",
    "allowed_gestures": ["talk", "greeting", "agreement"]
  }
}
```

На startup Unity валидирует mappings и безопасно использует neutral fallback.

Анимации:

- только с проверенной лицензией;
- `THIRD_PARTY_ASSETS.md`;
- root transforms baked;
- root motion off;
- humanoid mapping validated;
- body clips не меняют facial blendshapes.

---

# 26. Desktop Avatar Overlay

Требования:

- transparent background;
- borderless;
- optional always-on-top;
- click-through;
- drag mode;
- lock;
- scale;
- monitor selection;
- per-monitor DPI;
- restore position;
- off-screen recovery;
- show/hide hotkey;
- idle при закрытой панели;
- performance profiles.

Поддерживаемый Windows path:

- Direct3D 11;
- HDR off;
- alpha processing;
- standalone build;
- fallback ordinary borderless window.

Hit testing:

- default collider/raycast;
- opacity mode как optional;
- hotkey временно включает drag mode.

---

# 27. Desktop Shell

## 27.1. Выбор

```text
Tauri 2 + existing React
```

## 27.2. Ответственность

Tauri:

- single-instance;
- tray;
- autostart;
- process supervisor;
- global shortcuts;
- main control window;
- backend sidecar;
- Unity process;
- secrets;
- installer;
- crash UI;
- open logs;
- Safe Mode.

## 27.3. Startup

```text
Tauri starts
  → single-instance lock
  → load settings
  → choose loopback port
  → generate auth token
  → start backend
  → wait health
  → connect UI
  → start Unity
  → await avatar handshake
  → restore avatar position
```

## 27.4. Shutdown

```text
request graceful backend shutdown
  → close/checkpoint current episode
  → flush bounded pending jobs
  → avatar shutdown
  → bounded wait
  → terminate child tree
```

## 27.5. Fast startup

UI не ждёт полной загрузки всех моделей.

Показывать статусы:

```text
Core ready
STT loading
TTS loading
Avatar connecting
Memory index ready
```

## 27.6. Python packaging

Первый production path:

```text
PyInstaller --onedir
```

Не начинать с `--onefile`, потому что PyTorch, CTranslate2 и FFmpeg содержат много DLL и ухудшают startup/diagnostics.

---

# 28. Voice Live Mode

## 28.1. Pipeline

```text
Microphone
  → AudioWorklet PCM
  → Voice WebSocket
  → Ring Buffer
  → VAD
  → Utterance
  → STT
  → Context Manager
  → Character Agent
  → streaming LLM
  → TTS segments
  → PlaybackCoordinator
  → Unity
```

Push-to-talk остаётся fallback.

## 28.2. VAD states

```text
Idle
Listening
SpeechCandidate
Speech
EndPending
Finalizing
Transcribing
Thinking
Speaking
Interrupted
Error
```

## 28.3. Always available, не always recording

Различать:

```text
microphone monitoring
speech buffering
persisted recording
```

Default:

- короткий ring buffer в RAM;
- audio не пишется на диск;
- после utterance PCM уничтожается;
- raw audio storage выключен.

## 28.4. Wake modes

```text
Push-to-talk
Always-listening VAD
Optional wake phrase later
```

Wake word не обязателен для первой V0.5.

## 28.5. Barge-in

При речи пользователя во время ответа:

1. VAD debounce подтверждает речь.
2. Создаётся новая generation.
3. Старый LLM request отменяется.
4. TTS queue очищается.
5. UI playback останавливается.
6. Unity получает `avatar.stop`.
7. Late segments игнорируются.
8. Старое assistant message получает `interrupted`.
9. Новая utterance сохраняет pre-roll.

Цель:

```text
P95 confirmed speech → playback stopped ≤ 300 ms
```

---

# 29. Audio Ownership

Создать `PlaybackCoordinator`.

```text
owner = unity
owner = desktop_ui
owner = none
```

Правила:

- только один owner;
- lease выдаётся на utterance;
- reconnect Unity не получает середину старой utterance;
- owner change отменяет старую queue;
- generation обязательна;
- completion подтверждается owner;
- browser fallback не запускается, если Unity уже говорит.

---

# 30. Echo и false barge-in

Главный риск — микрофон слышит голос самой Нейро.

Защита:

- WebRTC echo cancellation;
- noise suppression;
- automatic gain control;
- playback reference;
- correlation gate;
- transcript similarity;
- VAD threshold boost во время TTS;
- minimum speech duration;
- headphones recommendation;
- half-duplex compatibility mode.

Не обещать идеальный full duplex на любых колонках.

---

# 31. STT

Оставить `faster-whisper`.

Profiles:

```text
Eco: CPU/int8 или лёгкая модель
Balanced: CUDA/int8_float16
Quality: более крупная модель
```

Добавить:

- partial transcript UI;
- language confidence;
- no-translate prompt;
- custom vocabulary/hotwords, где возможно;
- mic calibration;
- device change recovery;
- timeout;
- cancellation;
- warmup;
- diagnostics.

Partials не отправлять в основной LLM до final transcript.

---

# 32. TTS

Оставить Silero baseline.

Разделить:

```text
visible_reply
spoken_reply
```

`spoken_reply`:

- убирает markdown;
- нормализует числа;
- обрабатывает ссылки;
- сокращает code blocks;
- делит текст по естественным фразам;
- не меняет смысл.

Capabilities interface:

```python
class TTSCapabilities(BaseModel):
    streaming: bool
    languages: set[str]
    voices: bool
    style_control: bool
    rate_control: bool
    pitch_control: bool
    local: bool
```

Это позволит позже менять provider без переписывания orchestration.

---

# 33. Resource Management

RTX 3080 одновременно используется Unity и STT.

Default Balanced:

```text
Unity 30 FPS
Whisper CUDA
Silero CPU
VAD ONNX CPU
Embeddings CPU/background
```

Добавить Resource Manager:

- model load states;
- queue lengths;
- selected devices;
- GPU memory errors;
- fallback mode;
- optional embedding unload;
- performance presets.

При OOM:

1. отменить inference;
2. выгрузить optional models;
3. retry в lightweight mode;
4. показать warning;
5. не ронять приложение.

---

# 34. Persistent Settings

Runtime settings не должны исчезать после restart.

Sections:

```text
General
Companion
Personality
Voice Input
STT
TTS
Avatar
Memory
History
Performance
Providers
Storage
Diagnostics
```

Settings имеют:

- schema version;
- migrations;
- validation;
- defaults;
- section reset;
- export/import.

Secrets:

- Windows Credential Manager;
- DPAPI/keyring;
- `.env` только development.

---

# 35. Model Manager

Управляет:

```text
Whisper models
Silero TTS
Silero VAD
Embedding model
avatar asset metadata
```

UI:

- installed;
- size;
- version;
- progress;
- checksum;
- location;
- repair;
- remove;
- update.

Каталоги:

```text
%LOCALAPPDATA%\NeuroAsist\
  data\
  models\
  logs\
  cache\
  backups\
```

---

# 36. Privacy

## Audio

По умолчанию:

- не сохранять raw microphone audio;
- ring buffer только RAM;
- TTS cache очищать;
- debug recording только explicit toggle.

## Incognito Episode

Режим:

```text
Не сохранять текущий разговор
```

Тогда:

- сообщения только в RAM;
- summaries не создаются;
- memories не извлекаются;
- после episode данные удаляются.

## Memory deletion

Удаление memory очищает:

- canonical row/status;
- FTS;
- vector;
- caches;
- context cache;
- affected summaries помечаются stale.

## Timeline deletion

При удалении периода спросить:

```text
Удалить только историю?
Удалить также memories, основанные только на этой истории?
```

---

# 37. Observability

Correlation IDs:

```text
relationship_id
timeline_id
episode_id
message_id
utterance_id
generation
request_id
```

Metrics:

```text
speech start/end
final transcript latency
first LLM token
first TTS segment
first playback
utterance completion
barge-in stop
episode summary duration
memory extraction duration
context build duration
```

Context telemetry:

- selected memory IDs;
- selected episode IDs;
- token estimate;
- retrieval scores;
- compact reason.

Не хранить полный hidden prompt в normal mode.

---

# 38. API

## Timeline

```text
GET    /timeline
GET    /timeline/messages
GET    /timeline/journal
GET    /timeline/search
POST   /timeline/messages
POST   /timeline/stop
DELETE /timeline/range
```

## Episodes

```text
GET    /episodes
GET    /episodes/{id}
POST   /episodes/current/close
POST   /episodes/{id}/resummarize
DELETE /episodes/{id}
```

## Memory

```text
GET    /memory
POST   /memory
PATCH  /memory/{id}
DELETE /memory/{id}
POST   /memory/{id}/restore
POST   /memory/{id}/confirm
POST   /memory/{id}/reject
POST   /memory/reindex
POST   /memory/clear
```

Development only:

```text
POST /debug/context/preview
GET  /debug/context/last
```

---

# 39. Background Jobs

Не вводить Celery/Redis.

Использовать:

- controlled asyncio task manager;
- SQLite job table для recoverable jobs;
- bounded concurrency;
- graceful shutdown.

Jobs:

```text
episode_summary
memory_extraction
memory_index_update
embedding_rebuild
context_cache_cleanup
audio_cleanup
```

```sql
CREATE TABLE background_jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_text TEXT
);
```

Summarization и memory extraction не блокируют ответ.


---

# 40. Failure Modes

## LLM недоступна

- timeline сохраняется;
- episode остаётся;
- summary job retry later;
- backend не падает;
- UI показывает понятный degraded state.

## STT упал

- text input работает;
- mic UI показывает ошибку;
- provider можно перезапустить.

## TTS упал

- текстовый ответ остаётся;
- optional system/browser fallback;
- avatar emotion может примениться без речи.

## Unity упал

- backend продолжает разговор;
- desktop UI становится playback owner;
- supervisor предлагает restart.

## Memory index упал

- FTS fallback;
- основной ответ не блокируется;
- vector mode отмечается degraded.

## DB risk

Использовать:

- WAL;
- periodic backup;
- integrity check;
- migration backup;
- restore tool.

---

# 41. Testing Strategy

## Timeline

- append/order;
- idempotency;
- correction;
- cancellation;
- restart recovery;
- deletion range;
- export;
- migration старого `default`.

## Episodes

- inactivity boundary;
- application restart;
- calendar transition;
- context pressure;
- отсутствие empty episodes;
- продолжение после короткой паузы;
- закрытие после длинной;
- summary retry;
- manual close.

## Context

- personality всегда присутствует;
- current message всегда присутствует;
- turn pairing;
- token budget;
- priority trimming;
- relevant episode selection;
- irrelevant episode rejection;
- deleted memory excluded;
- current correction overrides old memory.

## Memory

- extraction precision;
- source validation;
- duplicate;
- supersede;
- sensitive confirmation;
- forget;
- restore;
- FTS fallback;
- vector failure;
- temporal retrieval;
- deletion leakage.

## Voice

- VAD states;
- pre-roll;
- silence;
- barge-in;
- stale generation;
- audio owner;
- reconnect;
- mic disconnect;
- echo false positives.

## Avatar

- schema compatibility;
- emotion transitions;
- gesture cancellation;
- transparency;
- click-through;
- restore position;
- frame performance.

---

# 42. Evaluation

## Context Continuity

Сценарии:

- продолжение через 5 минут;
- продолжение через 2 часа;
- продолжение на следующий день;
- ссылка на решение недельной давности;
- смена темы;
- возвращение к старой теме;
- correction;
- удалённая история;
- incognito episode.

Metrics:

```text
continuity accuracy
irrelevant recall rate
false-memory rate
context token cost
summary factuality
open-loop recovery accuracy
```

## Memory

Категории:

```text
exact fact
paraphrase
multi-episode
temporal
update
correction
conflict
irrelevant
abstention
sensitive
deletion
```

Начальные targets:

```text
write precision ≥ 90%
retrieval recall@5 ≥ 80%
deleted-memory leakage = 0
confirmed correction success = 100%
```

Targets подтверждаются benchmark, а не считаются гарантированными.

## Live Soak

Проверить:

- несколько часов idle/interaction;
- десятки episodes;
- сотни turns;
- Unity reconnect;
- backend restart;
- suspend/resume;
- API outage;
- mic disconnect;
- TTS failure;
- memory reindex;
- отсутствие zombie processes;
- отсутствие роста очередей.

---

# 43. Definition of Done

Задача готова только если:

- код реализован;
- tests добавлены;
- старые tests проходят;
- async operation cancellable;
- есть timeout;
- есть typed error;
- migration и rollback проверены;
- UI имеет loading/error/empty state;
- docs обновлены;
- нет absolute paths;
- dependency pinned;
- logs redacted;
- acceptance доказан test/smoke;
- background failure не ломает live conversation.

---

# 44. Поэтапный план V0.5

## Milestone 0 — Freeze и воспроизводимость

### Цель

Зафиксировать V0.4.1 и открыть Codex доступ ко всем частям. Если сделанно то пропускай и переходи к Milestone 1

### Задачи

- создать ветку `v0.5`;
- добавить этот blueprint;
- удалить из roadmap V0.5 Dev Agent;
- зафиксировать continuous companion concept;
- подключить Unity source;
- убрать absolute paths;
- version manifest;
- V0.4.1 DB fixture;
- baseline tests;
- baseline latency;
- smoke script.

### Acceptance

- clean clone запускает backend/web;
- Unity source доступен;
- compatibility versions известны;
- DB fixture тестируется;
- runtime behavior не изменён.

---

## Milestone 1 — Versioned Storage и Unified Timeline

### Цель

Заменить `default` history на одну корректную временную линию.

### Backend

- migration system;
- relationship/timeline;
- append-only messages;
- statuses;
- idempotency;
- input modes;
- correction events;
- pagination;
- journal API;
- compatibility adapter.

### Frontend

- восстановление истории;
- последние сообщения;
- Journal;
- search;
- stop/retry;
- удаление range;
- никакого списка чатов.

### Acceptance

- история переживает restart;
- порядок стабилен;
- duplicate request не дублируется;
- V0.4.1 messages мигрируются;
- пользователь видит одну timeline.

---

## Milestone 2 — Episode Manager

### Цель

Автоматически делить timeline на разговорные эпизоды.

### Задачи

- episode tables;
- active lifecycle;
- inactivity boundaries;
- startup recovery;
- calendar boundary;
- context pressure;
- manual close;
- journal grouping;
- boundary events;
- settings thresholds.

### Acceptance

- короткая пауза продолжает episode;
- длинная создаёт новый;
- empty episodes отсутствуют;
- crash/restart обрабатывается;
- пользователь не управляет episodes вручную.

---

## Milestone 3 — Summarization и Context Manager

### Цель

Убрать бесконечный raw context и обеспечить continuity.

### Задачи

- structured summaries;
- background summary jobs;
- rolling/final summary;
- Context Manager;
- model-aware token budget;
- recent turn window;
- old episode retrieval;
- diagnostics;
- context eval fixtures.

### Acceptance

- старые messages не отправляются целиком;
- важные решения сохраняются;
- context укладывается в budget;
- summary failure не блокирует разговор;
- continuity после restart работает.

---

## Milestone 4 — Tauri Desktop Shell

### Цель

Перевести систему в настоящий desktop companion mode.

### Задачи

- `apps/desktop`;
- Tauri;
- reuse React;
- tray;
- single-instance;
- backend sidecar;
- random port/token;
- Unity lifecycle;
- graceful shutdown;
- crash recovery;
- global shortcuts;
- show/hide avatar;
- Safe Mode;
- PyInstaller onedir spike.

### Acceptance

- один запуск стартует всё;
- UI не требует browser tab;
- avatar можно скрыть/показать;
- child processes завершаются;
- backend crash отображается и восстанавливается.

---

## Milestone 5 — Long-Term Memory V1

### Цель

Добавить управляемую память поверх episodes.

### Задачи

- memory schema;
- audit;
- extraction;
- policy;
- source validation;
- dedupe;
- conflicts;
- corrections;
- FTS5;
- retrieval;
- Memory Center;
- privacy modes;
- incognito;
- leakage tests.

### Acceptance

- каждая memory имеет source;
- пользователь может изменить/удалить;
- deleted memory не попадает в context;
- automatic memory отключаема;
- history и memory очищаются отдельно.

---

## Milestone 6 — Semantic Retrieval

### Цель

Добавить поиск по смыслу без жёсткой привязки.

### Задачи

- VectorIndex;
- Null implementation;
- sqlite-vec implementation;
- embedding provider;
- multilingual benchmark;
- hybrid fusion;
- temporal retrieval;
- reindex;
- fallback;
- explanation.

### Acceptance

- FTS работает без vectors;
- index rebuildable;
- dimensions не смешиваются;
- semantic mode включается только при улучшении eval.

---

## Milestone 7 — Character Protocol v3

### Цель

Унифицировать текст, эмоции, gestures и continuity references.

### Задачи

- canonical schema;
- generated types;
- one emotion enum;
- metadata frames;
- ContinuityCue;
- deterministic fallback;
- persona config;
- relationship-aware prompt;
- v1/v2 adapter.

### Acceptance

- live и batch используют одну schema;
- metadata не видна;
- invalid metadata не ломает reply;
- Python/TS/C# parity проверяется CI.

---

## Milestone 8 — Emotion Engine и Avatar Overlay

### Цель

Сделать аватара живым и пригодным для постоянного рабочего стола.

### Задачи

- emotion state machine;
- smooth transitions;
- mapping validation;
- gesture priorities;
- gaze/idle polish;
- transparent D3D11;
- click-through;
- drag/lock;
- scale;
- monitors/DPI;
- position restore;
- performance profiles.

### Acceptance

- overlay стабилен;
- desktop не блокируется;
- emotion не дёргается;
- старые gestures не ломают новые;
- позиция восстанавливается.

---

## Milestone 9 — Live Voice, VAD и Barge-in

### Цель

Перейти от push-to-talk к живому разговору.

### Задачи

- AudioWorklet PCM;
- input WebSocket;
- ring buffer;
- Silero VAD;
- voice state machine;
- mic calibration;
- PlaybackCoordinator;
- generation/cancellation;
- barge-in;
- echo safeguards;
- half-duplex fallback;
- partial transcript UI;
- device recovery.

### Acceptance

- hands-free mode работает;
- push-to-talk остаётся;
- пользователь перебивает ответ;
- late audio не проигрывается;
- Unity и UI не говорят одновременно;
- raw mic audio не сохраняется default.

---

## Milestone 10 — Settings, Models и Installer

### Цель

Сделать продукт устанавливаемым.

### Задачи

- persistent settings;
- secure secrets;
- first-run wizard;
- Model Manager;
- installer;
- clean VM;
- diagnostics;
- backup/export;
- retention;
- uninstall choices.

### Acceptance

- нет ручных terminal commands;
- models загружаются с progress;
- API keys не plain text;
- uninstall не удаляет память без подтверждения;
- release build воспроизводим.

---

## Milestone 11 — Stabilization Gate

### Цель

Не добавлять новые функции до доказанной стабильности.

### Задачи

- context eval;
- memory eval;
- voice latency;
- avatar performance;
- soak;
- crash injection;
- backup/restore;
- migration tests;
- privacy review;
- license audit;
- bug fixing only.

### Release Gate

V0.5 готова, если:

- одна timeline работает;
- episodes создаются корректно;
- summaries не теряют важные решения;
- Context Manager держит budget;
- память прозрачна;
- deletion не протекает;
- desktop shell управляет процессами;
- avatar overlay стабилен;
- barge-in работает;
- installer работает на clean Windows;
- длительная работа не деградирует.

---

# 45. Первые change sets для Codex

```text
1. docs(v0.5): replace chat-based plan with continuous companion blueprint
2. chore(avatar): pin Unity source and remove absolute paths
3. feat(storage): add versioned migrations
4. feat(timeline): add primary relationship and unified timeline
5. feat(timeline): migrate old default-session messages
6. feat(episodes): add automatic episode lifecycle
7. feat(summary): add structured episode summaries
8. feat(context): replace recent-N history with ContextManager
9. feat(desktop): add Tauri shell and backend supervision
10. feat(memory): add memory schema, audit and FTS retrieval
11. feat(web): add Journal and Memory Center
12. feat(memory): add optional semantic retrieval adapter
13. feat(protocol): add Character Protocol v3
14. feat(avatar): add emotion engine and desktop overlay
15. feat(voice): add VAD, audio ownership and barge-in
16. feat(release): add model manager and installer
```

---

# 46. Критические риски

## Episode fragmentation

Риск: слишком много episodes.

Защита:

- time rules;
- minimum turns;
- topic classifier не включать сразу;
- metrics;
- manual merge/debug tool.

## Episodes слишком длинные

Защита:

- max token estimate;
- context pressure;
- rolling summary;
- forced close.

## Summary искажает историю

Защита:

- source message IDs;
- structured schema;
- factuality eval;
- resummarize;
- raw history остаётся canonical.

## Memory повторяет summary

Защита:

- разные schemas;
- importance threshold;
- dedupe;
- отдельные retrieval namespaces.

## Персонаж слишком часто вспоминает прошлое

Защита:

- relevance threshold;
- prompt rule;
- continuity cue;
- over-reference evaluation.

## Удалённая информация остаётся в summary

Защита:

- dependency tracking;
- stale summaries;
- resummarization;
- leakage test.

## Live mode слышит самого себя

Защита:

- AEC;
- playback reference;
- debounce;
- threshold boost;
- half-duplex fallback.

## Desktop app большой

Это ожидаемо из-за Unity, Python и models.

Цель — один installer и управляемая загрузка моделей, а не один маленький binary.

## Scope explosion

Dev Agent, screen context и stream integrations запрещены до release gate.

---

# 47. Правила работы Codex

Перед изменением Codex обязан:

1. Прочитать текущую реализацию.
2. Найти существующие tests.
3. Зафиксировать поведение.
4. Работать одной вертикальной задачей.
5. Не создавать параллельную архитектуру без причины.
6. Обновлять docs.
7. Добавлять tests.
8. Сохранять backward compatibility.
9. Использовать feature flags.
10. Не давать LLM прямой DB write.

Feature flags:

```env
TIMELINE_V2_ENABLED=false
EPISODES_ENABLED=false
CONTEXT_MANAGER_ENABLED=false
MEMORY_ENABLED=false
MEMORY_VECTOR_ENABLED=false
DESKTOP_MANAGED_MODE=false
AVATAR_PROTOCOL_V3_ENABLED=false
VOICE_VAD_ENABLED=false
VOICE_BARGE_IN_ENABLED=false
```

---

# 48. Короткая сводка

## Что удалено из прошлого плана

```text
система отдельных чатов
ручное создание диалогов
chat sidebar как основа продукта
```

## Что добавлено

```text
одна общая timeline
автоматические episodes
episode summaries
Context Manager
Journal по времени
relationship continuity
долгосрочная память
```

## Что видит пользователь

```text
одна Нейро
один общий разговор
одна общая история
одна память
```

## Что находится внутри

```text
timeline
episodes
summaries
memories
recent context
```

## Новый порядок

```text
1. Зафиксировать V0.4.1 и Unity source
2. Единая timeline
3. Автоматические episodes
4. Summaries и Context Manager
5. Tauri desktop shell
6. Long-term memory
7. Semantic retrieval
8. Character Protocol v3
9. Эмоции и desktop avatar
10. VAD и barge-in
11. Installer
12. Стабилизация
```

Главная мысль: NeuroAsist должна ощущаться не как программа, где пользователь открывает чаты, а как один постоянно существующий персонаж с общей жизнью и историей отношений.

---

# 49. Источники и ориентиры

## Текущий проект

- https://github.com/bad1and/NeuroAsist/tree/v0.4.1
- https://github.com/bad1and/NeuroAsist/blob/v0.4.1/README.md
- https://github.com/bad1and/NeuroAsist/blob/v0.4.1/Docs/neuro_vtuber_assistant_blueprint_v1.1.md
- https://github.com/bad1and/NeuroAsist/blob/v0.4.1/apps/backend/app/agents/character/agent.py
- https://github.com/bad1and/NeuroAsist/blob/v0.4.1/apps/backend/app/storage/sqlite_history.py
- https://github.com/bad1and/NeuroAsist/blob/v0.4.1/apps/backend/app/avatar/service.py

## Comparable projects

- https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- https://github.com/moeru-ai/airi

## Desktop/Avatar

- https://v2.tauri.app/develop/sidecar/
- https://v2.tauri.app/reference/config/
- https://github.com/kirurobo/UniWindowController

## Memory

- https://arxiv.org/abs/2410.10813
- https://github.com/mem0ai/mem0
- https://www.sqlite.org/fts5.html
- https://github.com/asg017/sqlite-vec

## Voice

- https://github.com/snakers4/silero-vad
