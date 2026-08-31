# Iris 1.0 — текущий статус

Обновлено: **21 августа 2026**. Историческая V0.5 milestone-карта выполнена и
перенесена в архив. Текущая задача — доказать release-quality уже реализованной
системы, а не добавлять новые крупные подсистемы.

## Состояние функциональных контуров

| Контур | Статус | Что реализовано | Что проверяется перед public release |
| --- | --- | --- | --- |
| Timeline и episodes | готово | Versioned SQLite, unified timeline, summaries, Journal | Migration/restore на копиях старых данных |
| Character и context | готово | Protocol v3, bounded context, state, reflections | Поведенческий eval после prompt compression |
| Long-term memory | готово, quality gate | Background consolidation, provenance/audit, FTS/semantic retrieval | Recall/precision corpus и token budget |
| Text и live voice | готово, soak gate | PCM/VAD/Smart Turn, streaming TTS, barge-in, reconnect leases | Часовой real-audio soak и latency baseline |
| Desktop shell | готово, installer gate | Tauri lifecycle, token auth, tray, safe mode, single instance | Clean-VM install/upgrade/uninstall |
| Unity avatar | готово, soak gate | VRM/lip sync/gestures, overlay и in-app режимы | Длительный lifecycle/performance test |
| Settings и models | готово | Atomic runtime settings, Credential Manager, Model Manager | Recovery и filesystem failure checks |
| Coding Agent | готово, optional | Docker sandbox, durable queue, diff/review/apply | Security matrix и Docker availability UX |
| LLM cost controls | готово, measurement gate | Thinking policy, max tokens, retry budget, usage telemetry | 30-minute cost baseline и alert thresholds |
| Public release | не одобрен, CI подготовлен | Version metadata, docs, CI/candidate artifact pipeline | Все пункты release checklist и evidence на конкретном commit |

## Завершённые stabilization-пакеты

### 1. LLM usage control

- обычные профили явно отключают thinking;
- каждому назначению задан конечный output budget;
- retries ограничены общим budget;
- telemetry считает prompt/output/reasoning/cache/latency на физическую попытку.

### 2. Memory и prompt efficiency

- memory consolidation coalesces turns и пропускает неинформативный small talk;
- extraction input имеет жёсткий budget и компактный topic shortlist;
- character prompt разделён на стабильный cache prefix и dynamic state;
- legacy memory protocol исключается там, где работает background extraction.

### 3. Runtime reliability

- устранён Model Manager install deadlock;
- background workers supervised и перезапускаются с bounded backoff;
- voice disconnect/reconnect/shutdown отменяет и дожидается stale tasks;
- settings persist-before-publish и используют atomic replace;
- SQLite/filesystem work вынесен из интерактивных async hot paths.

### 4. Version и документация

- `VERSION` задаёт `1.0.0`;
- npm, Cargo, Tauri, FastAPI и Unity metadata синхронизированы;
- README описывает реальный default-branch setup;
- current docs отделены от branch-specific archive;
- локальные ссылки и version drift проверяются автоматически.

## Открытые release gates

Приоритет определяется [release checklist](release-checklist.md):

1. поддерживаемый и проверенный backup restore;
2. clean Windows VM installer/upgrade/uninstall;
3. hour-long real voice/avatar soak с reconnect и barge-in;
4. memory/persona quality corpus и 30-minute LLM cost baseline;
5. artifact license/privacy/security audit;
6. прогон CI/release candidate pipeline на защищённом runner и подписанные checksums.

До закрытия этих пунктов `1.0.0` означает целевую версию исходного дерева и
internal release candidate, а не разрешение публиковать stable installer.

## Навигация

- [Архитектура](architecture.md)
- [Эксплуатация](operations.md)
- [Release checklist](release-checklist.md)
- [Versioning](versioning.md)
- [Исторические планы](archive/README.md)
