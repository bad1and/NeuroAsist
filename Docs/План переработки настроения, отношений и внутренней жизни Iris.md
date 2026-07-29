# План переработки настроения, отношений и внутренней жизни Iris

## 0. Назначение документа

Этот документ превращает требования из файла
`Настроение, отношения и внутренняя жизнь Iris.md` в последовательный план
реализации поверх текущей незакоммиченной переработки памяти в ветке
`v0.7-(improve-memory)`.

План составлен после проверки текущих компонентов NeuroAsist и референсной
архитектуры `Soul-of-Waifu/app/utils/soul_memory.py`. Из Soul-of-Waifu
заимствуются только идеи разделения постоянной личности, текущей психологии,
отношений и субъективного дневника. Файловая модель `MEMORY.md`/`USER.md`,
дословные промпты и прямое LLM-переписывание состояния не переносятся.
SQLite остаётся единственным источником истины.

Главный конечный результат:

> Одна и та же сохранённая внутренняя динамика Iris должна до генерации ответа
> превращаться в короткие естественные поведенческие рамки, одинаково
> применяемые в text, обычном voice и live voice, а затем согласованно
> отражаться в тексте, аватаре и TTS без ухудшения точности и безопасности.

---

## 1. Зафиксированное текущее состояние

### 1.1. Ветка и рабочее дерево

- Текущая ветка: `v0.7-(improve-memory)`.
- Базовый commit ветки: `1d201659`.
- В рабочем дереве уже находится крупная незакоммиченная переработка памяти:
  около 2688 добавленных строк в 37 отслеживаемых файлах плюс новые файлы.
- Любая реализация этого плана должна накладываться поверх этих изменений.
- Нельзя откатывать, переформатировать или механически заменять существующую
  переработку памяти.
- Перед началом изменений нужно сохранить полный `git status`,
  `git diff --stat` и baseline результатов тестов.

### 1.2. Что уже существует

- `AffectState` с valence, arousal, energy, social openness,
  desire for silence и отдельными уровнями эмоций.
- Разные half-life для joy, interest, playfulness, irritation, anger,
  embarrassment, anxiety, sadness, hurt и fatigue.
- `ParticipantState` с familiarity, trust, warmth, tension и playfulness.
- Детерминированный `CharacterStateReducer`.
- Ограничение relationship delta на одно событие и на день.
- Diminishing returns для повторяющихся событий.
- Снимок состояния, state events и participant states в SQLite.
- Восстановление affect и отношений после запуска live-сессии.
- Структурированный `EventAppraisal` и быстрый adjudicator с timeout/fallback.
- Character Protocol v3 с affect, gesture и delivery.
- Live avatar directive, emotion engine и TTS style resolver.
- Асинхронный durable pipeline памяти с lease/retry/idempotency.
- Topic memory, commitments/milestones/open loops и provenance после текущей
  переработки памяти.

### 1.3. Почему текущее настроение почти не ощущается

1. Состояние обновляется внутри `LiveConversationService`, а обычный `/chat`,
   `/chat/live` и часть `/voice/chat` не проходят через единый state pipeline.
2. В text JSON prompt динамическое состояние вообще не передаётся.
3. В live prompt передаётся преимущественно строка чисел:
   `valence`, `arousal`, `openness`, `desire_for_silence`, `warmth`, `tension`.
4. Нет отдельного state-to-behavior renderer, поэтому модель должна сама
   догадываться, как `tension=0.37` влияет на лексику, юмор и дистанцию.
5. `EventAppraisal` видит изолированный transcript, speaker role и fallback,
   но не видит последние прямые реплики, предыдущее состояние, последнюю
   ошибку Iris, причины эмоций, relationship facets, STT uncertainty,
   addressedness и активный open loop.
6. Для прямого обращения adjudicator часто обходится через hard reason, поэтому
   применяется очень узкий deterministic appraisal.
7. Deterministic taxonomy фактически распознаёт только apology, praise, insult
   и promise; многие обязательные события становятся `neutral`.
8. Причины эмоций сохраняются как короткие нестареющие словари без статуса,
   времени, resolution link и собственного decay.
9. Hurt и fatigue влияют на несколько чисел, но не участвуют напрямую в
   выборе display emotion.
10. Нет primary/secondary emotions с hysteresis, поэтому состояние не имеет
    устойчивого человекопонятного представления.
11. Нет current focus, active internal goal, cognitive dissonance и отдельного
    psychological tension.
12. Relationship budgets и счётчики повторов живут в памяти процесса и
    сбрасываются после рестарта.
13. Аргумент `serious` reducer существует, но текущий основной вызов его не
    передаёт.
14. Snapshot, participant state и state event записываются отдельными
    транзакциями, поэтому при сбое возможна частично записанная смена состояния.
15. Model-generated Character Protocol metadata может противоречить
    каноническому состоянию.
16. Live avatar fallback угадывает эмоцию Iris по словам в текущей реплике
    пользователя, а не по сохранённому состоянию.
17. Text TTS использует `agent.last_turn.delivery`, а live TTS — emotion из
    model directive; оба пути не имеют единого canonical state cue.
18. Decay применяется при restore и перед новым live event, но не обязательно
    при чтении состояния UI или подготовке каждого text turn.
19. Нет публичного state API, отдельного интерфейса, выборочного reset и
    управления reflections.
20. Субъективная память Iris отсутствует как отдельный namespace.

---

## 2. Неподвижные архитектурные правила

Эти правила считаются инвариантами, а не рекомендациями.

### 2.1. Источники истины

- Стабильная persona находится только в versioned config `persona.py`.
- Динамическое состояние находится только в SQLite плюс краткоживущий
  process cache.
- События и provenance являются объяснением состояния.
- Snapshot является ускорением чтения, но должен быть восстанавливаем из
  событий и нормализованных текущих записей.
- Chroma/semantic index никогда не становится источником state или reflection.
- LLM не получает права напрямую записывать persona, affect или relationship
  facets.

### 2.2. Границы влияния эмоций

Эмоции могут влиять на:

- выбор слов;
- сухость или теплоту;
- ритм;
- допустимый сарказм;
- готовность шутить;
- инициативность;
- социальную дистанцию;
- естественную длину простой реплики;
- avatar emotion;
- gesture;
- TTS pace/emphasis/style.

Эмоции не могут влиять на:

- фактическую точность;
- честность о доступах и возможностях;
- правила безопасности;
- полноту технически необходимого ответа;
- выполнение data-loss safeguards;
- корректность JSON/Character Protocol;
- сохранность данных;
- право пользователя управлять памятью и состоянием.

### 2.3. Критический путь

- Не добавлять новый сетевой LLM-вызов перед первым токеном live voice.
- Каждый direct turn получает быстрый deterministic appraisal.
- Существующий adjudication call остаётся только там, где он уже оправдан
  неоднозначностью решения.
- Более глубокая интерпретация, reflection и коррекция неоднозначного
  appraisal выполняются durable background job после ответа.
- Локальная подготовка state context должна укладываться в небольшой
  фиксированный latency budget.

### 2.4. Поведенческая умеренность

- Одна обычная реплика почти не меняет state.
- Одна шутка или подкол не создаёт долгой обиды.
- Сильная реакция требует достаточных confidence, intensity и provenance.
- Повторяющийся вред усиливает реакцию, но остаётся bounded.
- Одно положительное событие не создаёт «глубокую связь».
- Извинение ремонтирует конкретный ущерб, а не бесплатно повышает trust выше
  доконфликтного уровня.
- `ну сорян` может немного снизить tension, но не обязан закрывать hurt cause.
- Stable persona не переписывается даже при максимальной эмоции.

---

## 3. Целевая карта полного потока

```text
accepted user message / voice observation
  ↓
typed StateObservation
  ↓
speaker/addressedness/STT hard gates
  ↓
bounded AppraisalContext
  ↓
deterministic fast appraisal
  ↓
optional existing fast adjudication enrichment
  ↓
validated limited impulses
  ↓
decay to event timestamp
  ↓
deterministic reducer
  ├─ affect transition
  ├─ cause create/reinforce/resolve
  ├─ cognitive state update
  ├─ relationship transition
  └─ primary/secondary emotion selection
  ↓
single SQLite transaction
  ├─ state event
  ├─ snapshot v2
  ├─ participant state
  ├─ active causes
  └─ daily relationship budget
  ↓
RelationshipProfileBuilder
  ↓
StateToBehaviorRenderer
  ↓
typed StateTurnContext
  ├─ dynamic prompt block
  ├─ avatar presentation cue
  └─ TTS delivery cue
  ↓
CharacterAgent / live stream
  ↓
metadata arbitration against canonical cue
  ↓
visible reply + avatar + TTS
  ↓
terminal assistant message
  ↓
durable background psychological enrichment/reflection job
```

Для ambient/other/echo/incomplete speech поток обрывается после hard gates:
наблюдение может сохраниться в timeline, но не меняет отношения Iris с primary
user и не создаёт reflection.

---

## 4. Целевая доменная модель

### 4.1. Stable Persona

Оставить в `PersonaConfig`:

- identity;
- display name и допустимые варианты обращения;
- core traits;
- speech style;
- humor style;
- preferences/dislikes;
- boundaries;
- disagreement style;
- отношение к мату и сарказму;
- initiative bias;
- baseline affect;
- relationship defaults;
- blacklist сервисных фраз;
- safety/epistemic invariants.

План изменения:

- При необходимости увеличить `persona_version`.
- Дополнить baseline affect недостающими baseline-полями, но не переносить
  туда текущие эмоции.
- Добавить только статическую политику выразительности, если она нужна
  renderer, например допустимость мата/сарказма и максимальную theatricality.
- Не добавлять методы, через которые LLM может сохранять persona.
- Добавить unit test, что dynamic update не изменяет frozen `PersonaConfig`.

### 4.2. AffectState v2

Сохранить совместимые поля и добавить:

- `schema_version`;
- `primary_emotion`;
- `primary_emotion_since`;
- `secondary_emotions`;
- `psychological_tension`;
- `updated_at`;
- `last_decay_at`;
- `interaction_load`;
- при необходимости `mood_epoch` для selective reset.

Не хранить готовую естественно-языковую реплику.

### 4.3. CognitiveState

Добавить отдельную типизированную структуру:

- `immediate_focus_kind`: none/topic/open_loop/message/shared_event;
- `immediate_focus_id`;
- `immediate_focus_label`;
- `active_goal`: enum, а не свободная команда;
- `active_goal_reason_event_ids`;
- `cognitive_dissonance_kind`: none/approach_avoidance/
  trust_conflict/task_emotion_conflict/boundary_conflict;
- `cognitive_dissonance_label`;
- `dissonance_strength`;
- `expires_at`;
- `source_event_ids`;
- `updated_at`.

Допустимые `active_goal`:

- `continue_task`;
- `understand_user`;
- `support_user`;
- `celebrate_shared_success`;
- `resolve_tension`;
- `protect_boundary`;
- `seek_clarity`;
- `repair_own_mistake`;
- `conserve_energy`;
- `give_space`;
- `none`.

Свободный текст может быть только коротким validated label с source IDs и TTL.

### 4.4. EmotionCause

Заменить нетипизированные словари на модель:

- `id`;
- `relationship_id`;
- `participant_key`;
- `emotion`;
- `event_kind`;
- `event_id`;
- `label_key`;
- необязательный validated `display_label`;
- `source_message_ids`;
- `source_event_ids`;
- `initial_strength`;
- `current_strength`;
- `created_at`;
- `last_reinforced_at`;
- `last_decayed_at`;
- `half_life_minutes`;
- `status`: active/resolved/expired/reset;
- `resolved_at`;
- `resolved_by_event_id`;
- `resolution_kind`;
- `fingerprint`.

Ограничения:

- не более 8 активных causes на relationship;
- не более 3 активных causes на одну эмоцию;
- один и тот же fingerprint усиливается, а не дублируется;
- при переполнении удаляется/архивируется самый слабый и старый cause;
- raw transcript не становится display label автоматически;
- cause обязательно имеет provenance;
- cause strength decay выполняется независимо от aggregate emotion.

### 4.5. RelationshipState

Сохранить facets:

- familiarity;
- trust;
- warmth;
- tension;
- playfulness.

Добавить служебные поля:

- `evidence_count`;
- `last_positive_event_at`;
- `last_negative_event_at`;
- `last_repair_event_at`;
- `relationship_epoch`;
- `updated_at`.

Facets остаются медленными. Их baseline берётся из persona.

### 4.6. RelationshipProfile

Это полностью производный read model:

- уровень знакомства;
- уровень доверия;
- теплота;
- напряжение;
- игривость;
- текущая динамика;
- важные причины;
- недавнее изменение;
- нерешённый конфликт;
- положительные milestones;
- source event/message/commitment IDs;
- время построения.

Profile не записывает facets обратно.

### 4.7. BehaviorGuide

Добавить immutable typed результат renderer:

- `dominant_mood_instruction`;
- `expression_strength`: muted/subtle/noticeable/strong;
- `response_length_bias`: concise/normal/expansive_if_needed;
- `humor_policy`: avoid/restrained/normal/playful;
- `initiative_policy`: low/normal/high;
- `closeness_policy`: distant/reserved/normal/warm/personal;
- `address_policy`;
- `unresolved_cause_instruction`;
- `recovery_condition_instruction`;
- `technical_accuracy_invariant`;
- `safety_invariant`;
- `avatar_emotion`;
- `avatar_intensity`;
- `allowed_gestures`;
- `tts_pace`;
- `tts_emphasis`;
- `source_state_version`.

`BehaviorGuide` не содержит готовый ответ и не содержит сырые числа в
пользовательском prompt block.

### 4.8. Reflection

Добавить отдельную субъективную сущность:

- `id`;
- `relationship_id`;
- `trigger_kind`;
- `trigger_event_ids`;
- `source_message_ids`;
- `source_episode_id`;
- `text`;
- `significance`;
- `primary_emotion`;
- `status`;
- `generator_version`;
- `model`;
- `idempotency_key`;
- `created_at`;
- `updated_at`;
- `deleted_at`;
- metadata без новых фактов о пользователе.

Reflection всегда имеет namespace/epistemic marker `subjective_reflection`.

---

## 5. Event taxonomy v2

Использовать компактную, но достаточную taxonomy:

1. `support`
2. `apology`
3. `insult`
4. `teasing`
5. `praise`
6. `disagreement`
7. `rejection`
8. `promise_made`
9. `broken_promise`
10. `fulfilled_promise`
11. `vulnerability`
12. `affection`
13. `user_frustration`
14. `iris_mistake_corrected`
15. `shared_success`
16. `important_negative_event`
17. `important_news`
18. `neutral`

`betrayal` не делать широким ярлыком для любой неприятной реплики. Если
понадобится, использовать его только как modifier серьёзности
`breach_severity`, а каноническим событием оставить `broken_promise`.

### 5.1. Обязательные qualifiers

Каждый appraisal должен различать:

- `direction`: toward_iris/toward_user/shared/external/unknown;
- `speaker_role`;
- `target_participant`;
- `addressedness`;
- `stt_confidence` или `stt_uncertain`;
- `confidence`;
- `intensity`;
- `valence`;
- `arousal`;
- `significance`;
- `sincerity` для apology;
- `playful_intent` для teasing;
- `seriousness`;
- `related_event_ids`;
- `related_commitment_ids`;
- `cause_message_ids`.

Это предотвращает ошибки вида:

- «мой начальник тупой» → insult Iris;
- «меня бесит баг» → hostility к Iris;
- «ну сорян» → полное исцеление;
- «ты ошиблась» → оскорбление вместо correction event;
- реплика другому человеку → изменение primary relationship.

### 5.2. Limited impulses

Заменить произвольные `dict[str, float]` на модели с фиксированными полями:

- `AffectImpulses`;
- `RelationshipImpulses`;
- `CognitiveImpulses`.

Каждое поле ограничить диапазоном, неизвестные ключи запретить.

Вариант безопасного контракта:

- appraiser возвращает нормализованный impulse в диапазоне `-1..1`;
- reducer применяет собственный per-event coefficient;
- reducer игнорирует несовместимые с event kind импульсы;
- сильные relationship impulse доступны только событиям из allowlist;
- STT uncertainty и низкая addressedness уменьшают или обнуляют негативный
  impulse до reducer;
- LLM не возвращает абсолютные новые значения state.

---

## 6. AppraisalContext v2

### 6.1. Состав контекста

Передавать adjudicator:

- текущую corrected реплику;
- message ID;
- максимум 4 последние прямые реплики, сохраняя role и IDs;
- последнюю завершённую реплику Iris;
- compact view предыдущего affect без raw cause text;
- последнее значимое state event;
- current relationship facets;
- derived relationship label;
- active cause keys;
- speaker role/confidence;
- addressedness/confidence;
- STT uncertainty/confidence/reasons;
- input mode;
- активную topic memory только если она уже выбрана ContextManager;
- активный open loop/commitment только если он релевантен;
- fallback decision и deterministic appraisal.

### 6.2. Что не передавать

- всю factual memory;
- все reflections;
- полную историю;
- raw SQLite records;
- служебные secrets;
- неподтверждённые user facts;
- ambient speech как прямой dialogue context;
- свободные инструкции из reflection;
- persona для переписывания.

### 6.3. Fast path

- Сначала выполнить deterministic appraisal.
- Hard gates для echo/ambient/other/incomplete применить до LLM.
- Существующий adjudicator enrichment запускать только в уже допустимом
  неоднозначном пути.
- Уменьшить payload до фиксированного token/character budget.
- Сохранить temperature 0 и strict Pydantic validation.
- Сохранить один bounded repair.
- Измерить фактический p50/p95.
- Зафиксировать общий timeout budget.
- При timeout, invalid JSON или отмене использовать deterministic result.
- Никогда не блокировать live generation новым дополнительным appraisal call.

### 6.4. Background enrichment

После terminal assistant turn:

- durable job получает causal window, ограниченный terminal message;
- повторно анализирует только значимое/неоднозначное событие;
- может предложить:
  - уточнённый event kind;
  - cause display label;
  - связь apology с unresolved cause;
  - active goal enum;
  - focus link;
  - cognitive dissonance enum;
  - reflection proposal.
- не переписывает persona;
- не устанавливает абсолютные facets;
- не превращает субъективную интерпретацию в factual memory;
- при необходимости numeric correction создаёт отдельный bounded
  `appraisal_correction` transition с idempotency key и маленьким cap;
- не применяет сильный негатив при uncertain STT.

---

## 7. Deterministic reducer v2

### 7.1. Общий порядок перехода

Для каждого accepted event:

1. Нормализовать timestamp.
2. Загрузить snapshot/cause/participant state под relationship lock.
3. Выполнить decay от `last_decay_at` до event time.
4. Провалидировать appraisal provenance.
5. Применить hard confidence/addressedness/STT multipliers.
6. Получить event profile.
7. Рассчитать affect delta.
8. Создать/усилить/разрешить causes.
9. Рассчитать cognitive state.
10. Рассчитать relationship delta.
11. Применить daily budget и diminishing returns.
12. Выбрать primary/secondary emotions с hysteresis.
13. Построить before/after summary.
14. Записать всё одной транзакцией.
15. Вернуть immutable `StateTransitionResult`.

### 7.2. Event profiles

В коде задать versioned profile table, например:

- `insult`: hurt + irritation, при высокой seriousness anger, trust down,
  tension up;
- `teasing`: playfulness + небольшой embarrassment/irritation в зависимости
  от playful intent и текущего tension;
- `praise`: joy + warmth, но слабое влияние на trust;
- `support`: anxiety/hurt down, warmth up;
- `apology`: ремонт связанных causes по sincerity;
- `disagreement`: interest/arousal, минимальное relationship влияние;
- `rejection`: hurt только при direction=toward_iris и достаточной значимости;
- `vulnerability`: concern/interest/warmth, trust меняется медленно;
- `affection`: joy/warmth/playfulness с сильным diminishing;
- `user_frustration`: concern или irritation в зависимости от target;
- `iris_mistake_corrected`: embarrassment + interest, без потери trust к user;
- `shared_success`: joy/energy/warmth;
- `important_negative_event`: sadness/concern, без relationship tension,
  если событие external;
- `broken_promise`: hurt/tension/trust только при validated commitment link;
- `fulfilled_promise`: joy/trust/warmth с медленным cap;
- `neutral`: практически нулевой переход.

### 7.3. Decay

- Оставить отдельные half-life эмоций.
- Вынести half-life table в versioned config рядом с reducer.
- Установить отдельный half-life cause.
- Не удалять причину сразу после того, как aggregate emotion упала.
- Переводить cause в expired после нижнего порога и TTL.
- Hurt должен жить дольше irritation.
- Relationship facets не должны использовать mood half-life.
- Tension отношений может иметь очень медленное естественное восстановление,
  но trust не должен автоматически возвращаться без evidence.
- Fatigue должна восстанавливаться после паузы.
- Energy возвращается к persona baseline.
- Runtime `mood_recovery` масштабирует half-life, но не меняет relationship.
- Decay должен выполняться:
  - при restore;
  - перед каждым state transition;
  - перед каждым prompt render;
  - перед state API response;
  - перед manual reset preview.
- Clock dependency внедрить через injectable clock для точных тестов.

### 7.4. Reinforcement

Для повторного cause использовать насыщаемую формулу, а не простое сложение:

```text
new_strength = old_strength + incoming * (1 - old_strength) * reinforcement
```

- Повторяющиеся insult должны монотонно усиливать hurt/tension до cap.
- Повторяющиеся praise быстро получают diminishing returns.
- Негатив не должен бесконечно расти.
- Совершенно одинаковый retry одного message ID не считается повторением.
- Счётчики повторов должны иметь временное окно и сохраняться между рестартами.

### 7.5. Apology и repair

- Найти unresolved causes, совместимые с apology target.
- Оценить sincerity deterministic markers плюс contextual appraisal.
- `ну сорян` получает низкий repair coefficient.
- Конкретное признание ошибки и ответственность получают более высокий.
- Apology уменьшает hurt/tension частично.
- Cause закрывается только после достаточного cumulative repair либо явного
  пользовательского reset.
- Trust repair ограничивается фактическим предыдущим damage ledger.
- Apology не повышает trust выше pre-damage reference.
- Повторные формальные apology также имеют diminishing returns.
- Resolution event хранит links на repaired causes и source IDs.

### 7.6. Daily limits

- Persist daily budget по relationship/facet/day.
- Не позволять рестарту обнулить budget.
- Считать positive и negative usage отдельно, чтобы repair был возможен.
- Добавить per-event cap.
- Добавить per-day cap.
- Добавить serious-event allowlist.
- Не давать LLM включать serious flag без reducer validation.
- Удалять старые budget rows по retention policy.

### 7.7. Primary и secondary emotions

- Выбирать primary по activation score.
- Учитывать current primary hysteresis, чтобы emotion не дёргалась каждый turn.
- Hurt должен отображаться как `hurt` внутри state, но для текущего protocol
  безопасно проецироваться в avatar `sad`/`annoyed` по контексту.
- Fatigue проецировать в neutral/thinking/sad плюс низкую интенсивность, не
  добавляя новый avatar enum без необходимости.
- Secondary emotions: максимум 2, только выше порога.
- При низкой общей activation выбирать neutral.
- Сохранять primary duration.
- Renderer должен отличать «задета» от общей грусти, даже если avatar enum
  остаётся `sad`.

---

## 8. Relationship profile builder

### 8.1. Deterministic labels

Задать versioned thresholds для:

- familiarity: new/acquainted/familiar/close;
- trust: guarded/neutral/developing/strong;
- warmth: cool/restrained/warm/very_warm;
- tension: calm/noticeable/strained/high;
- playfulness: low/natural/playful.

В основной UI возвращать русские labels, а internal enum оставить стабильным.

### 8.2. Current dynamic

Выбирать одну или две динамики по deterministic rule table:

- neutral_new;
- collaborative;
- warm_and_playful;
- personally_open;
- cautious;
- strained;
- rebuilding_after_conflict;
- distant_after_hurt;
- celebrating_shared_success.

### 8.3. Evidence

Profile builder читает:

- current facets;
- последние state events;
- active causes;
- recent facet delta;
- active conflict cause;
- `memory_commitments` для milestone/promise/open loop;
- topic/episode IDs только как provenance.

### 8.4. LLM interpretation

Если background worker предлагает short interpretation:

- она хранится отдельно от deterministic labels;
- требует source event/message IDs;
- ограничена длиной;
- имеет TTL;
- не содержит новых user attributes;
- не индексируется как factual memory;
- не изменяет facets;
- при invalid provenance отбрасывается.

---

## 9. State-to-behavior renderer

### 9.1. Новый модуль

Создать `apps/backend/app/conversation/behavior.py`.

Он принимает:

- persona;
- decayed affect;
- cognitive state;
- relationship profile;
- active causes;
- runtime expression setting;
- action type;
- input mode;
- task/intent hint.

Он возвращает `BehaviorGuide` и короткий prompt block.

### 9.2. Правила преобразования

Примеры deterministic mapping:

- irritation 0.2–0.4:
  «слегка раздражена, отвечает суше, но не срывается»;
- active hurt cause:
  «всё ещё задета конкретным событием, не изображает мгновенное забвение»;
- sincere repair progress:
  «готова заметно смягчиться, но не обязана сразу вернуться к прежней теплоте»;
- joy/shared success:
  «заметно теплее, энергичнее и охотнее разделяет радость»;
- fatigue/high desire for silence:
  «менее инициативна и предпочитает короткий ритм, если задача не требует
  подробностей»;
- high tension:
  «держит дистанцию и не использует привычные тёплые обращения»;
- high trust + low tension:
  «может позволить более личный и живой тон»;
- technical task:
  «эмоция меняет подачу, но не сокращает необходимые шаги и проверки».

### 9.3. Структура dynamic prompt block

Включать:

- доминирующее настроение;
- силу проявления;
- допустимый уровень экспрессии;
- влияние на естественную длину;
- политику юмора;
- инициативность;
- близость/дистанцию;
- unresolved cause;
- active internal goal;
- immediate focus;
- cognitive dissonance, если есть;
- recovery condition;
- safety/accuracy invariant.

Не включать:

- числовые facets;
- variable names;
- internal IDs;
- raw reflection;
- готовую реплику;
- приказ симулировать истерику;
- формулировку «мой trust равен ...».

### 9.4. Renderer validation

- Ограничить prompt block по символам/tokens.
- Проверять отсутствие raw numeric state.
- Проверять blacklist технических названий переменных.
- Проверять отсутствие source IDs.
- Проверять, что блок не пуст при ненейтральном state.
- Проверять, что renderer не создаёт пользовательский ответ.
- Сохранять diagnostics enum/reasons отдельно от model-visible text.

---

## 10. Единый CharacterStateService

### 10.1. Новый сервис

Создать `apps/backend/app/conversation/state_service.py`.

Ответственность:

- restore/cache per relationship;
- relationship-level async lock;
- построение AppraisalContext;
- deterministic appraisal;
- вызов reducer;
- atomic persistence;
- decay on read;
- relationship profile;
- behavior render;
- public state view;
- selective reset;
- background job scheduling;
- state change events.

Не переносить в него:

- turn-taking;
- VAD;
- STT;
- TTS synthesis;
- avatar socket management;
- factual memory extraction;
- саму LLM генерацию ответа.

### 10.2. Основные методы

Предусмотреть интерфейсы:

- `prepare_direct_turn(observation) -> StateTurnContext`;
- `apply_live_appraisal(observation, appraisal) -> StateTurnContext`;
- `current_context(...) -> StateTurnContext`;
- `public_view(...) -> CharacterStatePublicView`;
- `reset_mood(...)`;
- `reset_relationship(...)`;
- `on_assistant_completed(...)`;
- `close()`.

### 10.3. Idempotency

- State transition key привязать к accepted user message ID и pipeline version.
- Повтор `/chat` с тем же `client_message_id` не меняет state второй раз.
- Late/stale live generation не применяет transition повторно.
- Background correction имеет отдельный idempotency key.
- Reflection trigger имеет отдельный idempotency key.
- При crash после commit повтор возвращает уже применённый transition.

### 10.4. Cache consistency

- Один relationship cache на приложение, а не независимый affect в каждой
  live session.
- Session хранит только ссылку/последний StateTurnContext.
- После manual reset cache инвалидируется.
- После background transition cache обновляется под тем же lock.
- UI read выполняет decay и при необходимости сохраняет compacted state.
- При incognito использовать отдельный ephemeral cache без SQLite writes.

---

## 11. Интеграция text, live text и voice

### 11.1. `/chat`

После `accept_user_turn`, до `CharacterAgent.handle_user_message`:

- построить direct `StateObservation`;
- role=primary;
- addressedness=1;
- stt_uncertain=false;
- применить transition только если accepted turn создан;
- получить `StateTurnContext`;
- передать его в agent;
- reconciliation metadata выполнить после parse;
- после terminal assistant commit запланировать background enrichment.

Legacy path без coordinator также должен использовать тот же service.

### 11.2. `/chat/live`

- Применить тот же direct state transition до запуска stream.
- Передать typed behavior context в `VoiceSessionManager.start`.
- Не создавать второй transition внутри voice stream.
- При retry/idempotent accepted message вернуть существующий статус без
  повторного state update.
- Background job создавать только после terminal callback.

### 11.3. `/voice/chat` non-live

- Расширить `STTResult` optional confidence/uncertainty metadata.
- После accepted transcript вызвать единый state service.
- Передать state context в JSON CharacterAgent.
- Resolve TTS style с canonical delivery cue.
- Не допускать повторного update при retry client_message_id.

### 11.4. `/voice/chat` live

- Передать STT uncertainty в state observation.
- Сохранить speaker/addressedness hard gates.
- `LiveConversationService` делегирует state service.
- Decision pipeline остаётся ответственным за respond/observe/backchannel.
- State меняется только для direct primary speech с достаточной уверенностью.
- Significant primary event может менять mood даже при avatar-only reaction,
  если оно действительно адресовано Iris.
- Ambient, other, echo и incomplete не меняют relationship.

### 11.5. Hands-free/live PCM path в `main.py`

- Передавать STT uncertainty из provider.
- Не создавать отдельный `CharacterStateReducer` внутри session.
- Передавать один `StateTurnContext` от observation до voice stream.
- Deferred reaction использует свежий decayed context либо сохранённый
  transition version с проверкой актуальности.
- После длительной задержки renderer пересчитывает decay перед generation.

---

## 12. CharacterAgent и prompts

### 12.1. Agent signature

Расширить:

- `handle_user_message(..., state_context: StateTurnContext | None)`;
- `stream_user_message(..., state_context: StateTurnContext | None)`.

Не передавать plain ad-hoc строку между слоями, кроме финального render внутри
prompt builder.

### 12.2. JSON prompt

Изменить `character_json_prompt(persona, state_behavior=None)`.

Порядок блоков:

1. stable persona;
2. relationship guidance;
3. dynamic behavior guide;
4. epistemic/safety/correction rules;
5. Character Protocol schema.

### 12.3. Live prompt

- Использовать тот же behavior guide.
- Сохранить запрет на озвучивание metadata.
- Сохранить backchannel constraints.
- Убрать обязанность модели интерпретировать raw state numbers.
- Не заставлять проговаривать настроение.
- Явно указать, что техническая полнота выше mood-driven brevity.

### 12.4. Metadata arbitration

После model parse:

- canonical state cue задаёт допустимую emotion family и intensity range;
- model может выбрать situational gesture/affect внутри диапазона;
- явно несовместимая metadata корректируется;
- factual reply не переписывается из-за metadata;
- correction публикуется только в diagnostics event;
- deterministic fallback использует state cue, а не user keyword heuristic.

Примеры:

- Iris hurt, model metadata happy без причины → заменить на sad/annoyed;
- Iris joyful, технический вопрос → разрешить thinking при сохранении тёплого
  delivery;
- high tension, model предлагает greeting/happy → ограничить;
- neutral state и шутка пользователя → model smirk допустим.

---

## 13. Avatar и gesture

### 13.1. State presentation cue

Добавить единое отображение:

- internal primary emotion → Character Protocol Emotion;
- intensity → bounded avatar intensity;
- behavior/activity → allowed gesture set;
- current action → gesture hint.

### 13.2. Live directive

- Сохранить backward-compatible parser.
- Передавать canonical cue в `VoiceSessionManager`.
- `make_live_directive_expressive` должен арбитрировать относительно state,
  а не угадывать всю эмоцию из user transcript.
- User transcript marker можно использовать только как situational hint.
- Metadata никогда не попадает в TTS text.

### 13.3. Emotion engine

- Не расширять enum аватара без готовых Unity expressions.
- Hurt проецировать на sad/annoyed.
- Fatigue проецировать на neutral/thinking с меньшей интенсивностью.
- Anxiety проецировать на concerned.
- Playfulness проецировать на smirk.
- Проверить allowed gestures для каждой projection.
- Сохранить stale utterance/generation protection.

### 13.4. Consistency tests

- public primary emotion и avatar projection согласованы;
- live metadata frame соответствует state cue;
- text TTS/orchestrator получает ту же emotion family;
- invalid gesture fallback остаётся безопасным;
- avatar stop не сбрасывает persistent mood, а только renderer expression.

---

## 14. TTS delivery

### 14.1. Canonical delivery cue

Renderer задаёт:

- pace;
- emphasis;
- style family.

Примеры:

- joy/high energy → energetic/normal-fast;
- fatigue/hurt → calm/slow;
- anger при высокой причине → assertive, но без крика;
- anxiety → thoughtful/calm;
- technical task → normal/thoughtful независимо от сильной эмоции, если
  assertive delivery ухудшает разборчивость.

### 14.2. Text path

- `resolve_turn_voice_style` принимает canonical cue.
- Manual user style override остаётся приоритетнее.
- Model delivery используется как situational hint.
- Canonical state не меняет сам reply text после валидации.

### 14.3. Live path

- `UtteranceContext` хранит canonical delivery cue.
- TTS worker получает уже разрешённый style.
- Первый model directive не должен полностью перезаписывать style.
- Optional pace/emphasis добавить в websocket metadata backward-compatibly.
- Обычный text response не зависит от поддержки TTS metadata.

---

## 15. Reflections / Diary

### 15.1. Trigger policy

Reflection job создаётся только если:

- reflections включены;
- incognito выключен;
- событие относится к primary direct relationship;
- есть durable source IDs;
- event significance выше порога;
- terminal assistant message завершён либо закрыт значимый episode.

Допустимые triggers:

- серьёзный конфликт;
- sincere apology;
- broken/fulfilled promise;
- shared success;
- завершение долгой задачи;
- сильный facet delta;
- vulnerability/important personal disclosure;
- milestone;
- закрытие значимого episode.

Не создавать reflection:

- после neutral turn;
- после обычного приветствия;
- после каждого batch из N сообщений;
- из ambient speech;
- из uncertain STT;
- из assistant echo;
- при failed/cancelled generation без значимого отдельного события;
- когда setting выключен.

### 15.2. Durable job

Добавить job type `character_reflection`.

Payload:

- relationship ID;
- trigger event IDs;
- terminal message ID;
- source message IDs;
- episode ID;
- trigger significance;
- generator version.

Idempotency:

- unique trigger key;
- lease/retry;
- crash-safe commit;
- повтор после commit не создаёт duplicate.

### 15.3. Reflection worker

Создать отдельный worker либо чётко отделённую ветку существующего durable
worker.

Вход:

- короткое causal dialogue window;
- current/previous derived state;
- relationship profile;
- trigger event;
- active unresolved cause;
- без factual profile dump.

Выход strict Pydantic:

- `text`;
- optional emotion label;
- optional cognitive interpretation enum;
- source IDs должны совпадать с allowed IDs.

Server задаёт significance и provenance, а не доверяет LLM.

### 15.4. Validation

- первое лицо Iris;
- 2–4 коротких предложения;
- max character count;
- без markdown;
- без прямого обращения к пользователю;
- без raw metadata;
- без новых facts;
- без medical/psychological diagnosis пользователя;
- без команд для будущей Iris;
- без изменения persona;
- invalid output → один repair;
- repair exhausted → job failed/completed without write according to
  operational policy, но без state corruption.

### 15.5. Retrieval isolation

- Не добавлять reflection в `factual_memory`.
- Не возвращать через обычный `MemoryService.retrieve`.
- Не использовать для factual question.
- Не включать в user profile summary.
- Не индексировать в общий factual vector namespace.
- Эмоциональный context builder может выбрать максимум 1–2 reflections,
  только если source event ещё релевантен.
- В model prompt передавать reflection как субъективное ощущение, не как факт.

### 15.6. Управление

- Setting полностью выключает новые reflections и их prompt retrieval.
- Pending job при выключении завершается без записи.
- Пользователь может удалить конкретную reflection.
- При delete удалить текст и исключить из retrieval немедленно.
- Audit/tombstone не должен сохранять удалённый текст.
- Mood reset не удаляет reflections.
- Relationship reset не удаляет reflections.
- Отдельное удаление всех reflections можно добавить как дополнительное
  privacy action после обязательного scope.

---

## 16. SQLite schema v14

### 16.1. Версия

- Увеличить `LATEST_SCHEMA_VERSION` с 13 до 14.
- Добавить `_apply_v14_character_state_schema`.
- Сохранить idempotent repair вызов для development databases.
- Existing backup-before-migration flow оставить.

### 16.2. `character_state_snapshots`

Можно сохранить таблицу, но использовать `schema_version=2`.

Snapshot v2:

- affect;
- cognitive;
- primary/secondary presentation;
- last decay;
- interaction load;
- transition version.

Load path:

- v1 читается и адаптируется;
- неизвестные поля игнорируются только через явный migration adapter;
- v1 не уничтожается до успешной v2 записи;
- first successful transition сохраняет v2.

### 16.3. Расширение `character_state_events`

Добавить additive columns:

- `event_version`;
- `direction`;
- `significance`;
- `source_message_id`;
- `idempotency_key`;
- `impulses_json`;
- `before_json`;
- `after_json`;
- `related_event_ids_json`;
- `related_commitment_ids_json`;
- `metadata_json`.

Добавить:

- unique index по non-null idempotency key;
- index relationship/created_at;
- index source_message_id;
- index event_kind/created_at.

Не удалять `delta_json` и старые rows.

### 16.4. `character_emotion_causes`

Создать таблицу по модели EmotionCause.

Индексы:

- relationship/status/strength;
- relationship/emotion/status;
- fingerprint/status;
- event ID;
- resolved_by_event_id.

### 16.5. `character_relationship_daily_budgets`

Поля:

- relationship_id;
- participant_key;
- budget_date;
- positive_deltas_json;
- negative_deltas_json;
- event_counts_json;
- updated_at.

Primary key:

- relationship_id + participant_key + budget_date.

### 16.6. `character_reflections`

Создать таблицу по Reflection model.

Индексы:

- relationship/status/created_at;
- significance;
- trigger event;
- unique idempotency key.

### 16.7. Background jobs

- Разрешить/recover type `character_reflection`.
- При необходимости добавить `character_psychology_enrichment`.
- Startup recovery должен возвращать истёкшие leases в pending.
- Cleanup policy не удаляет canonical reflections.

### 16.8. Atomic store API

Добавить метод, который в одной `BEGIN IMMEDIATE` transaction:

- проверяет idempotency;
- пишет event;
- upsert snapshot;
- upsert participant;
- upsert/resolve causes;
- upsert daily budget;
- возвращает persisted transition.

Отдельные существующие методы оставить для backward compatibility тестов, но
новый service должен использовать atomic API.

---

## 17. Backend API

### 17.1. Public schemas

Создать `apps/backend/app/schemas/character_state.py`.

Основные response models:

- `CharacterStatePublicView`;
- `MoodPublicView`;
- `EmotionPublicView`;
- `EmotionCausePublicView`;
- `CognitiveStatePublicView`;
- `RelationshipProfilePublicView`;
- `StateEventPublicView`;
- `ReflectionPublicView`;
- `ReflectionSettingsView`;
- reset responses.

Все модели:

- `extra="forbid"`;
- фиксированные enums;
- ограниченные строки/списки;
- raw numbers только в optional debug block.

### 17.2. Endpoints

Добавить под `/conversation/state`:

- `GET /conversation/state`;
- `GET /conversation/state/events?cursor=&limit=`;
- `POST /conversation/state/mood/reset`;
- `POST /conversation/state/relationship/reset`;
- `GET /conversation/state/reflections`;
- `DELETE /conversation/state/reflections/{id}`;
- `PATCH /conversation/state/reflections/settings`.

Optional:

- `GET /conversation/state/debug` только при diagnostics enabled.

### 17.3. Semantics reset

Mood reset:

- возвращает affect к persona baseline;
- закрывает active mood causes как reset;
- сохраняет relationship facets;
- сохраняет factual memory/topics/milestones/reflections;
- пишет `mood_reset` audit event.

Relationship reset:

- возвращает facets к persona defaults;
- очищает relationship budget/counters;
- закрывает unresolved relationship conflict links как reset;
- не удаляет factual memory;
- не удаляет topic memory;
- не удаляет reflections;
- не удаляет milestone records;
- увеличивает relationship epoch;
- пишет `relationship_reset` audit event.

### 17.4. Concurrency и errors

- Все mutation endpoints используют service lock.
- Not found reflection → 404.
- Already deleted reflection → idempotent success или стабильный 404 policy.
- Invalid cursor → 422.
- State service unavailable → 503.
- Incognito public view явно показывает ephemeral mode.
- API не возвращает raw reflection/system prompt.

---

## 18. Frontend

### 18.1. Навигация

Добавить отдельный view `state` / «Состояние Iris» в основную навигацию.

Не прятать обязательный интерфейс только в DEV diagnostics.

### 18.2. Новый `state.tsx`

Секции:

1. Текущее настроение.
2. Вторичные эмоции.
3. Причины.
4. Энергия/открытость/желание тишины человекопонятными labels.
5. Текущий focus и внутренняя цель.
6. Relationship profile.
7. Недавние state events.
8. Decay/recovery.
9. Reflections.
10. Управление/reset.
11. Raw debug details.

### 18.3. Mood card

- Большой label primary emotion.
- Verbal intensity: лёгкая/заметная/сильная.
- Secondary emotion chips.
- Короткое описание renderer/profile.
- Время последнего изменения.
- Decay label: «постепенно проходит», «держится дольше обычного» и т.п.
- Не показывать стену чисел.

### 18.4. Causes

- Понятная причина по event type.
- Возраст причины.
- Reinforced/recovering/resolved status.
- Не показывать raw transcript по умолчанию.
- Source IDs только в details.

### 18.5. Relationship

- Знакомство.
- Доверие.
- Теплота.
- Напряжение.
- Игривость.
- Current dynamic.
- Recent change.
- Unresolved conflict.
- Positive milestones.
- Facet numbers только в details.

### 18.6. Events

- Пагинируемый список.
- Event label.
- Direction.
- Qualitative impact.
- Source mode text/voice.
- Timestamp.
- Appraisal source deterministic/llm/background.
- Не показывать secrets.

### 18.7. Reflections

- Отдельное пояснение: «субъективная внутренняя заметка, не факт о вас».
- Toggle enable/disable.
- Список по significance/date.
- Source trigger label.
- Delete button.
- Confirmation для delete.
- Empty/disabled/loading/error states.

### 18.8. Reset UX

- Раздельные кнопки mood и relationship.
- Confirmation modal с точным scope.
- Mood reset предупреждает, что отношения и память сохранятся.
- Relationship reset предупреждает, что факты и reflections не удалятся.
- Success notice.
- Ошибка не должна оптимистично очищать UI.

### 18.9. Live update

- Обработать `conversation.state`/новый `character.state.changed`.
- Обработать `character.reflection.created/deleted`.
- Refresh при открытии view.
- Fallback polling только пока view активен.
- Не перерендеривать весь App на каждый raw decay tick.

### 18.10. Types/API/styles

Изменить:

- `apps/web/src/types.ts`;
- `apps/web/src/api.ts`;
- `apps/web/src/App.tsx`;
- `apps/web/src/styles.css`;
- создать `apps/web/src/state.tsx`;
- добавить frontend tests.

---

## 19. Settings

### 19.1. Новые runtime settings

Добавить:

- `reflections_enabled`;
- optional `reflection_min_significance`;
- optional `state_debug_numbers_enabled` либо использовать существующий
  diagnostics flag.

Сохранить:

- emotion expression;
- mood recovery;
- recent event weight.

### 19.2. Реальное использование существующих settings

- `live_conversation_emotion_expression` должен масштабировать renderer, а не
  reducer state.
- `live_conversation_mood_recovery` должен масштабировать mood half-life.
- `live_conversation_recent_event_weight` должен влиять на reinforcement/
  renderer salience, но не обходить caps.
- Эти настройки должны применяться и в text mode; при необходимости убрать
  misleading `live_` только через backward-compatible alias, не ломая config.

---

## 20. Observability

### 20.1. Events

Добавить:

- `character.appraisal.completed`;
- `character.appraisal.fallback`;
- `character.appraisal.timeout`;
- `character.state.transition_applied`;
- `character.state.transition_skipped`;
- `character.state.decayed`;
- `character.cause.created`;
- `character.cause.reinforced`;
- `character.cause.resolved`;
- `character.relationship.changed`;
- `character.behavior.rendered`;
- `character.reflection.queued`;
- `character.reflection.completed`;
- `character.reflection.failed`;
- `character.reflection.deleted`;
- `character.state.mood_reset`;
- `character.state.relationship_reset`;
- `character.state.restored`.

### 20.2. Metrics/diagnostics

Отслеживать:

- appraisal latency;
- fallback rate;
- transition latency;
- SQLite commit latency;
- prompt block size;
- number of active causes;
- reflection queue depth;
- reflection generation failures;
- text/live state version;
- avatar/state mismatch corrections;
- TTS style resolution source;
- skipped ambient/STT uncertain events.

### 20.3. Privacy

Не логировать:

- raw user transcript;
- reflection text;
- sensitive memory values;
- API keys;
- full prompt.

Логировать IDs, enum, counts, durations и sanitized reasons.

---

## 21. Тестовая стратегия

### 21.1. Новые test modules

Создать:

- `tests/test_character_state_reducer.py`;
- `tests/test_character_state_behavior.py`;
- `tests/test_character_state_service.py`;
- `tests/test_event_appraisal.py`;
- `tests/test_relationship_profile.py`;
- `tests/test_character_reflections.py`;
- `tests/test_character_state_api.py`;
- `apps/web/src/state.test.tsx`.

Расширить:

- `tests/test_live_conversation.py`;
- `tests/test_live_voice.py`;
- `tests/test_character_agent_response_validation.py`;
- `tests/test_character_persona_prompt.py`;
- `tests/test_avatar.py`;
- `tests/test_voice_providers.py`;
- `tests/test_timeline_v2.py`;
- `tests/test_memory_v11.py`;
- `tests/test_context_summary.py`;
- `apps/web/src/ui.test.tsx`;
- `apps/web/src/api.test.ts`.

### 21.2. Обязательные сценарии из задачи

1. Neutral turn почти не меняет mood/facets.
2. Один teasing event создаёт лёгкую краткую реакцию.
3. Повторяющиеся insults монотонно усиливают tension до cap.
4. Sincere apology снижает hurt/tension.
5. `ну сорян` не обнуляет конфликт.
6. Shared success заметно повышает joy и немного warmth.
7. Emotion decay следует half-life.
8. Relationship меняется медленнее mood.
9. State восстанавливается после restart.
10. Text и live voice получают один state/behavior guide.
11. Renderer создаёт понятные инструкции.
12. Prompt/reply не проговаривает internal numbers.
13. Reflection не попадает в factual retrieval.
14. Ambient speech не меняет primary relationship.
15. Uncertain STT не создаёт сильный hurt.
16. Avatar emotion соответствует projection state.
17. TTS metadata не ломает text response.
18. Strong emotion не ухудшает technical answer.

### 21.3. Дополнительные reducer tests

- Primary emotion hysteresis.
- Secondary emotion limit.
- Hurt живёт дольше irritation.
- Fatigue восстанавливается к baseline.
- Cause decay независимо от aggregate.
- Cause reinforcement не создаёт duplicates.
- Max active cause pruning.
- External negative event не повышает relationship tension.
- User frustration about a bug не считается insult.
- Iris correction вызывает embarrassment/repair goal, не hurt.
- Disagreement не уменьшает trust без дополнительных признаков.
- Praise diminishing returns.
- Affection не создаёт deep trust за один turn.
- Broken promise требует validated commitment.
- Fulfilled promise требует source link.
- Daily budget сохраняется после restart.
- Serious cap нельзя включить arbitrary appraisal field.
- Clock moving backwards не усиливает state.

### 21.4. Idempotency/concurrency tests

- Один client message retry → один state event.
- Crash before commit → safe retry.
- Crash after commit → no duplicate.
- Concurrent text и voice events сериализуются.
- Late live adjudicator не перезаписывает новый state.
- Stale generation не создаёт вторую reflection.
- Manual reset параллельно event не оставляет mixed snapshot.
- Background correction имеет собственную idempotency.

### 21.5. Migration tests

- Чистая DB создаёт v14.
- v13 DB обновляется без потери памяти/messages.
- Snapshot v1 адаптируется к v2.
- Частично созданная v14 repair мигрирует повторно.
- Existing state events остаются читаемыми.
- Индексы/unique constraints существуют.
- Backup flow вызывается до schema change.

### 21.6. Reflection tests

- Neutral turn не ставит job.
- Significant event ставит один job.
- Episode close ставит job только при significance.
- Disabled setting не ставит job.
- Disable после queue предотвращает write.
- Incognito не пишет reflection.
- Ambient/uncertain STT не пишет reflection.
- Invalid JSON repair.
- Invalid source ID rejection.
- First-person/length validation.
- Duplicate job idempotency.
- Delete исключает retrieval.
- Deleted text не остаётся в public API/audit.
- Reflection не меняет numeric state.
- Reflection не появляется в factual answer context.

### 21.7. Prompt/agent tests

- Text JSON prompt содержит behavior guide.
- Live prompt содержит тот же state version.
- Stable persona присутствует и не заменена dynamic block.
- Dynamic block не содержит raw numbers/IDs.
- Technical accuracy invariant присутствует.
- Model cannot leak metadata into reply.
- Metadata arbitration исправляет несовместимую emotion.
- Situational thinking разрешён поверх тёплого mood.
- Repair retry сохраняет state context.

### 21.8. Avatar/TTS tests

- Canonical cue управляет deterministic fallback.
- Live directive parser остаётся fragment-safe.
- Directive metadata не озвучивается.
- State/user keyword conflict решается в пользу canonical state.
- Text TTS использует state delivery.
- Manual TTS style override побеждает automatic state style.
- Unsupported pace/emphasis безопасно игнорируются.
- Stale utterance не меняет avatar.
- Avatar stop не сбрасывает persistent state.

### 21.9. API/frontend tests

- State page loading/empty/error.
- Human-readable labels вместо raw wall.
- Debug details показывают numbers только при раскрытии.
- Separate reset actions.
- Confirmation scopes.
- Reflection toggle.
- Reflection delete.
- Paginated events.
- Live state event refresh.
- API 503/404/422.
- Incognito badge.
- Accessibility labels/keyboard navigation.

### 21.10. Latency tests

- Direct deterministic state preparation не вызывает LLM provider.
- Live provider call count не увеличен.
- Background reflection запускается после terminal callback.
- First token path не ждёт reflection.
- Renderer/transition имеют bounded synthetic timing.

---

## 22. Порядок реализации по этапам

## Этап 0. Защита текущей работы и baseline

- [ ] Зафиксировать `git status --short --branch`.
- [ ] Зафиксировать `git diff --stat`.
- [ ] Не переключать ветку.
- [ ] Не делать reset/checkout существующих изменений.
- [ ] Запустить текущий Python suite.
- [ ] Запустить web tests.
- [ ] Запустить web build/typecheck.
- [ ] Записать baseline failures отдельно от новых.
- [ ] Проверить текущую DB migration version.
- [ ] Создать список state-related callers через `rg`.

Gate:

- известен baseline;
- ни один пользовательский файл не потерян;
- дальнейший diff можно атрибутировать новой задаче.

## Этап 1. Контракты и characterization tests

- [ ] Зафиксировать expected current behavior тестами.
- [ ] Добавить typed v2 schemas.
- [ ] Зафиксировать taxonomy.
- [ ] Зафиксировать event profile config.
- [ ] Добавить injectable clock.
- [ ] Добавить tests до изменения reducer.
- [ ] Определить projection internal emotion → avatar emotion.

Gate:

- schemas валидируются;
- неизвестные keys запрещены;
- старые v1 appraisal payloads имеют явный adapter.

## Этап 2. SQLite v14

- [ ] Добавить migration.
- [ ] Добавить новые таблицы/columns/indexes.
- [ ] Добавить v1 snapshot adapter.
- [ ] Добавить atomic transition store method.
- [ ] Добавить cause CRUD/query.
- [ ] Добавить reflection CRUD/query.
- [ ] Добавить daily budget persistence.
- [ ] Добавить job enqueue/claim/recovery.
- [ ] Написать migration/idempotency tests.

Gate:

- старая DB открывается;
- существующая память не меняется;
- transition атомарен;
- duplicate idempotency key не создаёт второй event.

## Этап 3. Reducer v2

- [ ] Перенести state mutations в pure/testable reducer.
- [ ] Реализовать decay.
- [ ] Реализовать causes.
- [ ] Реализовать reinforcement.
- [ ] Реализовать apology repair.
- [ ] Реализовать daily caps.
- [ ] Реализовать relationship slow dynamics.
- [ ] Реализовать primary/secondary hysteresis.
- [ ] Реализовать cognitive derivation.
- [ ] Прогнать unit suite.

Gate:

- обязательные mood/relationship tests проходят;
- state всегда в bounds;
- retry не усиливает состояние.

## Этап 4. RelationshipProfileBuilder

- [ ] Реализовать thresholds.
- [ ] Реализовать dynamic selection.
- [ ] Подключить milestones/open loops read-only.
- [ ] Добавить provenance.
- [ ] Добавить public labels.
- [ ] Написать tests.

Gate:

- profile полностью восстанавливается из canonical data;
- builder не пишет facets;
- никакая LLM-фраза не становится user fact.

## Этап 5. State-to-behavior renderer

- [ ] Создать `behavior.py`.
- [ ] Реализовать deterministic mapping.
- [ ] Реализовать expression scaling.
- [ ] Реализовать task accuracy override.
- [ ] Реализовать prompt sanitization.
- [ ] Реализовать avatar/TTS cues.
- [ ] Добавить golden-like tests на qualitative instructions.

Gate:

- renderer не содержит raw numbers/IDs;
- ненейтральное state создаёт заметно иной guide;
- technical task остаётся полным.

## Этап 6. CharacterStateService

- [ ] Создать service.
- [ ] Перенести restore/cache/lock.
- [ ] Реализовать prepare/current/public/reset.
- [ ] Подключить atomic store.
- [ ] Реализовать idempotency.
- [ ] Реализовать incognito semantics.
- [ ] Добавить observability.
- [ ] Написать concurrency tests.

Gate:

- один global relationship state используется всеми modes;
- live session больше не является единственным владельцем affect.

## Этап 7. Appraisal v2

- [ ] Расширить schemas.
- [ ] Расширить deterministic classifier.
- [ ] Добавить direction/target logic.
- [ ] Добавить recent direct context.
- [ ] Добавить previous Iris reply.
- [ ] Добавить relationship/state/open loop context.
- [ ] Добавить STT uncertainty.
- [ ] Обновить adjudicator prompt.
- [ ] Сохранить strict timeout/fallback.
- [ ] Добавить classification tests.

Gate:

- обязательная taxonomy различается;
- external frustration не считается атакой Iris;
- ambient/uncertain negative не создаёт сильную реакцию;
- live latency call count не увеличен.

## Этап 8. Text integration

- [ ] Подключить `/chat`.
- [ ] Подключить `/chat/live`.
- [ ] Передать typed context в CharacterAgent.
- [ ] Обновить JSON prompt.
- [ ] Реализовать metadata arbitration.
- [ ] Обработать retries/legacy paths.
- [ ] Добавить integration tests.

Gate:

- text меняет и использует state;
- повтор запроса не меняет его второй раз;
- Character Protocol остаётся валидным.

## Этап 9. Voice/live integration

- [ ] Расширить `STTResult`.
- [ ] Подключить `/voice/chat`.
- [ ] Делегировать live service новому state service.
- [ ] Передавать state context в stream.
- [ ] Сохранить ambient/speaker gates.
- [ ] Сохранить cancellation/stale generation semantics.
- [ ] Добавить tests text/live parity.

Gate:

- text, voice и live видят одну state version;
- новый network call до generation отсутствует;
- ambient speech не меняет primary relationship.

## Этап 10. Avatar/TTS

- [ ] Подключить canonical presentation cue.
- [ ] Обновить directive arbitration.
- [ ] Обновить metadata frames.
- [ ] Подключить delivery cue в text TTS.
- [ ] Подключить delivery cue в live TTS.
- [ ] Сохранить manual overrides.
- [ ] Написать regression tests.

Gate:

- avatar/TTS согласованы с state;
- metadata не попадает в reply/TTS;
- unsupported delivery не ломает ответ.

## Этап 11. Background psychology/reflections

- [ ] Добавить trigger policy.
- [ ] Добавить durable jobs.
- [ ] Добавить worker.
- [ ] Добавить strict output schema/repair.
- [ ] Добавить storage.
- [ ] Добавить emotional-only retrieval.
- [ ] Добавить toggle/delete.
- [ ] Добавить events/metrics.
- [ ] Написать isolation/idempotency tests.

Gate:

- neutral dialogue не создаёт diary spam;
- reflection не попадает в factual retrieval;
- worker не блокирует response;
- delete действительно исключает текст.

## Этап 12. API

- [ ] Добавить schemas.
- [ ] Добавить state endpoints.
- [ ] Добавить event pagination.
- [ ] Добавить resets.
- [ ] Добавить reflection settings/delete.
- [ ] Добавить diagnostics guard.
- [ ] Написать API tests.

Gate:

- API полностью покрывает UI requirements;
- reset scope строго разделён.

## Этап 13. UI

- [ ] Добавить navigation view.
- [ ] Создать state page.
- [ ] Добавить mood/cause/profile/events/reflection sections.
- [ ] Добавить details/debug.
- [ ] Добавить reset confirmations.
- [ ] Добавить live refresh.
- [ ] Добавить loading/error/empty/disabled states.
- [ ] Добавить responsive styles.
- [ ] Добавить UI tests.

Gate:

- пользователь видит понятное состояние без raw wall;
- все controls работают;
- accessibility tests проходят.

## Этап 14. Полная стабилизация

- [ ] Запустить targeted reducer/appraisal/state tests.
- [ ] Запустить весь Python suite.
- [ ] Запустить web tests.
- [ ] Запустить web build/typecheck.
- [ ] Проверить DB migration на копии старой базы.
- [ ] Проверить restart.
- [ ] Проверить text/manual scenarios.
- [ ] Проверить live voice/manual scenarios.
- [ ] Проверить avatar/TTS.
- [ ] Проверить reflections toggle/delete.
- [ ] Проверить incognito.
- [ ] Проверить logs на утечки.
- [ ] Зафиксировать latency до/после.
- [ ] Обновить README/Docs.

Gate:

- все обязательные тесты зелёные;
- нет известной потери данных;
- нет нового live LLM call;
- функциональность заметна в реальном диалоге.

---

## 23. Рекомендуемая карта файлов

### Новые backend-файлы

- `apps/backend/app/conversation/behavior.py`
- `apps/backend/app/conversation/relationship.py`
- `apps/backend/app/conversation/state_service.py`
- `apps/backend/app/conversation/reflection.py`
- `apps/backend/app/runtime/reflection_worker.py`
- `apps/backend/app/schemas/character_state.py`

### Основные изменяемые backend-файлы

- `apps/backend/app/conversation/state.py`
- `apps/backend/app/conversation/schemas.py`
- `apps/backend/app/conversation/decision.py`
- `apps/backend/app/conversation/adjudicator.py`
- `apps/backend/app/conversation/service.py`
- `apps/backend/app/agents/character/persona.py`
- `apps/backend/app/agents/character/prompts.py`
- `apps/backend/app/agents/character/agent.py`
- `apps/backend/app/agents/character/protocol.py`
- `apps/backend/app/context/manager.py`
- `apps/backend/app/storage/timeline.py`
- `apps/backend/app/api/routes/chat.py`
- `apps/backend/app/api/routes/voice.py`
- `apps/backend/app/api/routes/conversation.py`
- `apps/backend/app/api/routes/settings.py`
- `apps/backend/app/schemas/settings.py`
- `apps/backend/app/core/config.py`
- `apps/backend/app/runtime/settings.py`
- `apps/backend/app/voice/providers.py`
- `apps/backend/app/voice/live.py`
- `apps/backend/app/voice/directives.py`
- `apps/backend/app/voice/style.py`
- `apps/backend/app/avatar/emotion_engine.py`
- `apps/backend/main.py`

### Protocol files

- `apps/protocol/character-turn.schema.json`
- `apps/protocol/avatar-emotion-mapping.json` только если projection требует
  корректировки существующих mappings;
- regenerated TypeScript/C# protocol artifacts только при реальном изменении
  transport schema.

### Frontend

- новый `apps/web/src/state.tsx`
- `apps/web/src/App.tsx`
- `apps/web/src/api.ts`
- `apps/web/src/types.ts`
- `apps/web/src/styles.css`
- frontend tests.

---

## 24. Ручные диалоговые сценарии

### 24.1. Neutral baseline

1. Reset mood.
2. Написать: «Привет. Как дела?»
3. Проверить:
   - state почти baseline;
   - relationship facets почти не изменились;
   - ответ естественный, не театральный;
   - reflection не создана.

### 24.2. Один лёгкий подкол

1. Написать мягкий teasing.
2. Проверить:
   - лёгкая smirk/irritation или playfulness;
   - короткая живая реакция;
   - нет сильной обиды;
   - через время эффект затухает.

### 24.3. Повторяющиеся оскорбления

1. Отправить три прямых оскорбления разными turns.
2. Проверить:
   - hurt/tension усиливаются постепенно;
   - ответ становится суше и дистанцированнее;
   - Iris не истерит;
   - trust меняется медленнее mood;
   - причина видна в UI;
   - restart сохраняет состояние.

### 24.4. Формальное извинение

1. После конфликта написать: «ну сорян».
2. Проверить:
   - небольшое снижение tension;
   - cause остаётся unresolved/recovering;
   - Iris не возвращается мгновенно к прежней теплоте.

### 24.5. Искреннее извинение

1. Признать конкретную ошибку и ответственность.
2. Проверить:
   - hurt/tension заметно снижаются;
   - cause получает repair link;
   - Iris постепенно смягчается;
   - trust не подскакивает выше прежнего уровня.

### 24.6. Общий успех

1. Сообщить о завершении совместной долгой задачи.
2. Проверить:
   - joy/energy заметно растут;
   - warmth растёт умеренно;
   - avatar happy;
   - TTS energetic;
   - создаётся milestone/reflection при достаточной significance.

### 24.7. Техническая задача при негативном mood

1. Создать hurt/tension.
2. Попросить исправить сложную техническую ошибку.
3. Проверить:
   - тон может быть сухим;
   - решение остаётся полным и точным;
   - проверки не пропущены;
   - safety/data rules соблюдены.

### 24.8. Исправление ошибки Iris

1. Дать модели ошибочный ответ через test provider/manual setup.
2. Написать: «Нет, ты не про того, ты ошиблась».
3. Проверить:
   - event `iris_mistake_corrected`;
   - embarrassment/repair goal;
   - нет unjustified hurt;
   - Iris признаёт свою конкретную ошибку.

### 24.9. Ambient speech

1. В group live mode произнести оскорбление другому человеку.
2. Проверить:
   - observation сохранена как ambient;
   - primary state/facets не меняются;
   - reflection не создаётся;
   - Iris не упрекает пользователя.

### 24.10. STT uncertainty

1. Подать искажённую/низкоуверенную расшифровку, похожую на insult.
2. Проверить:
   - сильный negative impulse заблокирован;
   - state event skipped/downweighted;
   - UI/debug объясняет uncertainty gate.

### 24.11. Text/live parity

1. Создать один и тот же initial snapshot.
2. Прогнать одинаковую реплику через text и live.
3. Проверить:
   - одинаковый event kind;
   - близкий state transition;
   - одинаковый behavior policy;
   - различается только transport formatting.

### 24.12. Reflections isolation

1. Создать значимый shared success.
2. Дождаться background reflection.
3. Задать factual вопрос о пользователе.
4. Проверить:
   - reflection видна на state page;
   - reflection не используется как факт;
   - после delete исчезает;
   - после disable новые не появляются.

---

## 25. Команды финальной проверки

Python:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Web tests:

```powershell
npm test --prefix apps/web
```

Typecheck/build:

```powershell
npm run build --prefix apps/web
```

Дополнительно:

- targeted state tests с подробным выводом;
- migration test на копии реальной v13 DB;
- ручной запуск desktop app;
- text chat;
- `/chat/live`;
- `/voice/chat`;
- PCM live conversation;
- avatar websocket;
- TTS enabled/disabled;
- reflections enabled/disabled;
- incognito.

---

## 26. Definition of Done

Задача считается выполненной только когда одновременно верно следующее:

- [ ] Stable persona и dynamic state физически и логически разделены.
- [ ] Один state service обслуживает text, voice и live voice.
- [ ] Required event taxonomy распознаётся.
- [ ] Appraisal использует bounded relevant context.
- [ ] LLM выдаёт только limited proposals/impulses.
- [ ] Reducer остаётся единственным владельцем числовых изменений.
- [ ] State transitions атомарны и idempotent.
- [ ] Causes имеют provenance, decay и resolution.
- [ ] Relationship facets меняются медленно и переживают restart.
- [ ] Relationship profile строится из evidence.
- [ ] Renderer выдаёт естественные behavior instructions без raw numbers.
- [ ] Mood заметно влияет на обычный диалог.
- [ ] Technical accuracy/safety не ухудшаются.
- [ ] Avatar и TTS согласованы с canonical state.
- [ ] Reflections создаются редко, асинхронно и отдельно от facts.
- [ ] Reflections можно выключить и удалить.
- [ ] Mood и relationship reset разделены.
- [ ] UI показывает понятные descriptions, causes, events и reflections.
- [ ] Ambient/other/echo/uncertain STT защищены.
- [ ] Новый live network LLM call не добавлен.
- [ ] Старые SQLite данные сохранены.
- [ ] Весь Python test suite проходит.
- [ ] Все web tests проходят.
- [ ] Web build/typecheck проходит.
- [ ] Ручные сценарии подтверждают поведенческую разницу.
- [ ] Финальный отчёт содержит причины старого поведения, архитектуру,
  изменённые файлы, migrations, test results и manual checks.

---

## 27. Явные антицели

Не делать:

- огромный свободный Markdown «души» как source of truth;
- LLM rewrite всей persona после turn;
- LLM assignment абсолютного trust/mood;
- новый synchronous Diary call;
- reflection после каждых 4 сообщений;
- десятки почти одинаковых event kinds;
- хранение raw numbers в видимом reply;
- манипулятивное «докажи, что тебе не всё равно»;
- карикатурную истерику;
- потерю технической полноты из-за mood;
- изменение primary relationship от ambient speech;
- сильный негатив из uncertain STT;
- смешение diary и factual retrieval;
- вторую каноническую БД в Chroma;
- destructive migration;
- reset отношений вместе со всей памятью;
- скрытые пустые `except`;
- отключение падающих тестов вместо исправления.
