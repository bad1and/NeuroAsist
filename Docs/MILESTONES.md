# NeuroAsist V0.5 — Milestones 0–11

Это единая карта работ по V0.5. Здесь находятся цель, результат и текущий статус каждого milestone. Детали реализации, API и тесты остаются в отдельных отчётах, на которые ведут ссылки ниже.

**Актуальный статус: 14 июля 2026.** Проект работает как локальный desktop companion; публичный release пока не готовится.

## Карта статусов

| № | Этап | Статус | Главный результат |
| --- | --- | --- | --- |
| 0 | Freeze и воспроизводимость | готово | Зафиксирована исходная версия и правила миграции к V0.5. |
| 1 | Versioned Storage и Unified Timeline | готово | Одна каноническая timeline вместо разрозненных сессий. |
| 2 | Episode Manager | готово | Внутренние эпизоды разговора, без отдельных пользовательских чатов. |
| 3 | Summarization и Context Manager | готово | Ограниченный и объяснимый контекст для LLM. |
| 4 | Tauri Desktop Shell | готово для development | Desktop-оболочка запускает и контролирует backend. |
| 5 | Long-Term Memory V1 | готово | Управляемая память с происхождением и аудитом. |
| 6 | Semantic Retrieval | готово, выключено по умолчанию | FTS-first поиск и опциональный семантический адаптер. |
| 7 | Character Protocol v3 | готово | Единый контракт ответа персонажа и аватара. |
| 8 | Emotion Engine и Avatar Overlay | частично готово | Emotion Engine готов; Unity overlay ждёт исходники Unity. |
| 9 | Live Voice, VAD и Barge-in | готово для локального режима | PCM, VAD, interruption и защита от late audio. |
| 10 | Settings, Models и Installer | готово для локального режима | Постоянные настройки, Credential Manager, Model Manager, backups. |
| 11 | Stabilization Gate | в работе | Регрессии пройдены; публичный release intentionally отложен. |

---

## Milestone 0 — Freeze и воспроизводимость

**Цель.** Зафиксировать V0.4.1 как исходную точку, прежде чем менять хранение истории и desktop-архитектуру.

**Сделано.** Описаны baseline, feature flags, совместимость старой истории и ожидания от Unity handoff.

**Результат.** Новые изменения не должны ломать старые `/chat`, `/voice/chat` и данные SQLite.

**Подробности:** [milestone-0-freeze.md](milestone-0-freeze.md).

## Milestone 1 — Versioned Storage и Unified Timeline

**Цель.** Убрать модель отдельных сессий и хранить разговор с одним companion в единой timeline.

**Сделано.** Добавлены версионные миграции SQLite, primary relationship/timeline, перенос legacy history и API timeline.

**Результат.** Один пользователь видит одну непрерывную историю; старые `session_id` сохраняются только как metadata для совместимости.

**Подробности:** [milestone-1-unified-timeline.md](milestone-1-unified-timeline.md).

## Milestone 2 — Episode Manager

**Цель.** Разбить timeline на внутренние смысловые эпизоды, не создавая пользователю «новые чаты».

**Сделано.** Добавлены правила пауз, лимитов сообщений/токенов, закрытия эпизодов и startup recovery.

**Результат.** Journal и последующая summarization получают понятные границы разговора.

**Подробности:** [milestone-2-episode-manager.md](milestone-2-episode-manager.md).

## Milestone 3 — Summarization и Context Manager

**Цель.** Заменить бесконтрольное «последние N сообщений» на ограниченный контекст с continuity.

**Сделано.** Summary jobs, rolling summary, token budget, diagnostics и безопасные fallback-сценарии.

**Результат.** В запрос LLM попадает identity, текущий контекст, релевантные summaries и недавние turns в пределах бюджета.

**Подробности:** [milestone-3-context-manager.md](milestone-3-context-manager.md).

## Milestone 4 — Tauri Desktop Shell

**Цель.** Сделать Tauri владельцем локального backend-процесса, UI и lifecycle приложения.

**Сделано.** Single instance, tray, Safe Mode, случайный loopback token, health check, контролируемый startup/shutdown и restart после crash.

**Результат.** В development desktop-окно автоматически запускает Python core и не открывает backend в сеть.

**Подробности:** [milestone-4-desktop-shell.md](milestone-4-desktop-shell.md), [desktop README](../apps/desktop/README.md).

## Milestone 5 — Long-Term Memory V1

**Цель.** Добавить устойчивые факты о пользователе и отношениях без скрытых записей в память.

**Сделано.** Memory items, candidate/confirm/reject flow, provenance, audit trail, разные режимы сохранения и Memory Center.

**Результат.** Память объяснима, редактируема и отдельно очищается от timeline.

**Подробности:** [milestone-5-long-term-memory.md](milestone-5-long-term-memory.md).

## Milestone 6 — Semantic Retrieval

**Цель.** Усилить обычный поиск по памяти семантическим поиском, но не делать его обязательным.

**Сделано.** FTS5 остаётся baseline; добавлены hash embedding provider, SQLite-compatible vector index, fusion и strict evaluation flag.

**Результат.** При проблемах с векторами система безопасно возвращается к FTS.

**Подробности:** [milestone-6-semantic-retrieval.md](milestone-6-semantic-retrieval.md).

## Milestone 7 — Character Protocol v3

**Цель.** Дать UI, voice и avatar одинаково понимаемый структурированный ответ персонажа.

**Сделано.** `CharacterTurn`, affect/gesture/delivery/continuity, JSON Schema, TypeScript и C# артефакты, fallback для старого формата.

**Результат.** Эмоция и намерение больше не извлекаются каждым потребителем по-своему.

**Подробности:** [milestone-7-character-protocol.md](milestone-7-character-protocol.md).

## Milestone 8 — Emotion Engine и Avatar Overlay

**Цель.** Превратить метаданные персонажа в предсказуемые эмоции, жесты и motion profile аватара.

**Сделано.** Emotion Engine, mapping JSON, arbitration команд, защита от stale stop и UI diagnostics.

**Ограничение.** Реальный прозрачный Unity overlay не реализован, потому что исходники Unity не переданы в репозиторий.

**Подробности:** [milestone-8-emotion-overlay.md](milestone-8-emotion-overlay.md), [unity-source.md](unity-source.md).

## Milestone 9 — Live Voice, VAD и Barge-in

**Цель.** Перейти от записи «нажал–сказал–отправил» к естественному разговору.

**Сделано.** Browser AudioWorklet PCM, input WebSocket, RAM-only ring buffer, Silero/energy VAD, barge-in, отмена generation, PlaybackCoordinator и push-to-talk fallback.

**Результат.** Hands-free слушает только при включённом режиме и не сохраняет сырой микрофонный звук по умолчанию.

**Подробности:** [milestone-9-live-voice.md](milestone-9-live-voice.md).

## Milestone 10 — Settings, Models и Installer

**Цель.** Сделать локальное приложение удобным для запуска без ручной настройки путей к моделям и ключам.

**Сделано.** Persistent runtime settings, first-run key setup через Windows Credential Manager, Model Manager с прогрессом и checksum, diagnostics, backup и retention. Данные desktop-режима живут в `%LOCALAPPDATA%\NeuroAsist`.

**Результат.** Локальный Tauri development-режим запускается одной командой; API key не попадает в JSON settings, backup или Git.

**Ограничение.** Полный публичный installer пока не является целью проекта; задача вынесена в `REL-001`.

**Подробности:** [milestone-10-release.md](milestone-10-release.md), [deferred-release-work.md](deferred-release-work.md).

## Milestone 11 — Stabilization Gate

**Цель.** Ничего нового не добавлять, пока не доказана устойчивость уже сделанного.

**Сделано на baseline.** Backend regression suite, web tests, desktop core smoke, миграции, backup/restore и privacy static scan прошли.

**Остаётся.** Context/memory evaluation corpus, voice latency, avatar performance, soak, crash injection и полноценный license audit. Public installer и clean Windows VM intentionally отложены, пока проект остаётся локальным.

**Подробности:** [milestone-11-stabilization.md](milestone-11-stabilization.md).

---

## Что открывать в обычной работе

1. Для цели и целевой архитектуры: [NeuroAsist_V0.5_Companion_Blueprint.md](NeuroAsist_V0.5_Companion_Blueprint.md).
2. Для текущего статуса работ: этот файл.
3. Для локального запуска и отложенного public release: [deferred-release-work.md](deferred-release-work.md).
4. Для конкретной реализации milestone: соответствующий `milestone-N-*.md`.

Старые blueprint-файлы с суффиксом `_old` находятся в [archive/](archive/) и являются историческими материалами, а не источником актуальных решений.
