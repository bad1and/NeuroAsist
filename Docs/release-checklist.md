# Release checklist Iris 1.0

Статус этого документа: **публичный релиз не одобрен**, пока каждый обязательный
пункт не подтверждён на конкретном commit/tag и Windows build artifact.

Заполняйте ссылки на логи, отчёты или checksums рядом с пунктами. Результат
локального development-запуска не заменяет проверку установщика.

## 1. Версия и исходники

- [ ] `VERSION`, npm, Cargo, Tauri, FastAPI и Unity показывают `1.0.0`.
- [ ] `python scripts/check_docs.py` проходит без исключений и битых ссылок.
- [ ] Release commit находится в чистом worktree и помечен тегом `v1.0.0`.
- [ ] Release notes перечисляют пользовательские изменения, миграции и известные ограничения.
- [ ] Сборка воспроизводится из нового clone по документированным командам.

## 2. Автоматические проверки

- [ ] Backend regression suite полностью зелёный.
- [ ] Web Vitest suite полностью зелёный.
- [ ] TypeScript/Vite production build зелёный.
- [ ] Rust `cargo check` зелёный.
- [ ] Desktop core smoke подтверждает token auth и graceful shutdown.
- [ ] Packaged core smoke проходит на собранном sidecar.
- [ ] Privacy/static scan не находит ключи, `.env`, пользовательскую БД или diagnostic audio в artifact.
- [ ] DeepSeek и Coding API вводятся только через настройки, хранятся раздельно в Windows Credential Manager и отсутствуют в environment ядра.
- [ ] Dependency scan не находит удалённые TTS/STT-библиотеки или `torchvision` в Python-sidecar.
- [ ] GitHub `CI` и `Documentation` прошли на release commit; ссылка на runs приложена.
- [ ] `Synthetic lifecycle soak` приложил успешный одночасовой report с RSS threshold.

Команды находятся в [operations.md](operations.md).

## 3. LLM и стоимость

- [ ] Обычные chat/live/memory/reflection/adjudication профили дают `reasoning_tokens = 0`.
- [ ] Основной ответ требует одного logical chat call; физические retries ниже 2% на контрольной сессии.
- [ ] Пустые/repair ответы не создают retry storm и соблюдают общий retry budget.
- [ ] Все назначения имеют конечный `max_tokens`; coding reasoning учитывается отдельно.
- [ ] Prompt cache hit/miss, input/output/reasoning tokens и latency видны в telemetry.
- [ ] Memory consolidation срабатывает не чаще установленного gate и показывает измеримое снижение input tokens относительно baseline.
- [ ] 30-минутный контрольный диалог укладывается в утверждённый token/cost budget.

## 4. Память и качество персонажа

- [ ] Eval corpus подтверждает сохранение явных просьб «запомни», corrections, preferences, goals и важных событий.
- [ ] Small talk и повтор уже известного факта не создают лишнюю consolidation job.
- [ ] Sensitive data следует выбранной policy и не активируется скрытно.
- [ ] Prompt compression не ухудшает persona, correction handling, ambient-speech decisions и JSON validity.
- [ ] Удаление/редактирование памяти отражается в retrieval и audit.
- [ ] Semantic index можно удалить и восстановить из SQLite без потери канонических данных.

## 5. Voice и avatar soak

- [ ] Не менее одного часа реального live voice без worker death, stale reply или неконтролируемого роста памяти. Synthetic CI soak не заменяет этот пункт.
- [ ] Disconnect/reconnect во время STT, LLM и TTS не публикует старый результат в новую сессию.
- [ ] Graceful stop допроводит подтверждённую реплику; forced disconnect её отменяет.
- [ ] Barge-in не останавливает чужую/новую generation.
- [ ] Background noise не вызывает ложную реплику на утверждённом microphone profile.
- [ ] First-text и first-audio latency записаны для clean/cached startup.
- [ ] Unity overlay и in-app режимы проходят часовой lip-sync/gesture test без orphan process.

## 6. Данные и восстановление

- [ ] Миграция копии данных предыдущей поддерживаемой версии проходит автоматически.
- [ ] Pre-migration backup создаётся до изменения schema.
- [ ] Backup ZIP проходит integrity check и не содержит API key.
- [ ] Документированный restore возвращает timeline, memory и settings на чистой установке.
- [ ] Повреждённая БД даёт понятную ошибку и не перезаписывается пустой.
- [ ] Reset memory/dialog/relationship выполняет только заявленный scope.
- [ ] Uninstall предлагает отдельный осознанный выбор: сохранить или удалить пользовательские данные.

> [!WARNING]
> В текущем UI есть создание/list/delete backup, но нет поддерживаемого restore.
> Публичный релиз нельзя одобрить, пока restore не реализован или не оформлен
> как проверенная пользовательская процедура.

## 7. Installer и чистая Windows VM

- [ ] NSIS устанавливается без Python, Node, Rust и terminal-команд.
- [ ] Product name, publisher, version и application identifiers корректны в installer и binaries.
- [ ] Первый запуск предлагает ключ и корректно работает после перезапуска.
- [ ] Safe Mode доступен при сломанном Unity/model preload.
- [ ] Model downloads показывают размер, progress, checksum, retry и удаление.
- [ ] Offline-поведение после предварительной загрузки понятно и проверено.
- [ ] Candidate не заявляет CUDA acceleration, если не поставлен и не проверен отдельный GPU runtime/add-on.
- [ ] Upgrade с предыдущей сборки сохраняет данные и не оставляет два autorun/single-instance registration.
- [ ] Uninstall удаляет binaries и managed processes без orphan files вне выбранных user data.

## 8. Security, privacy и licenses

- [ ] Backend desktop port принимает запросы только с session token.
- [ ] Secret не попадает в URL logs, settings, backup, crash report или UI event payload.
- [ ] Coding Agent подтверждён как Docker-only: no network, no host shell, no live mount, bounded resources.
- [ ] Source hash conflict блокирует применение coding patch поверх изменённого файла.
- [ ] Dependency и asset license audit завершён; notices включены в artifact.
- [ ] Mixamo/VRM/Unity assets распространяются в допустимой форме; исходные third-party assets не выдаются отдельным pack.
- [ ] Privacy notice ясно отделяет локальные STT/TTS от удалённых LLM requests.

## 9. Release decision

- [ ] Все обязательные пункты выше закрыты доказательствами.
- [ ] Известные ограничения перечислены в release notes.
- [ ] SHA-256 installer artifact опубликован вместе с версией и commit SHA.
- [ ] Manifest candidate artifact фиксирует SHA-256, commit, pre-NSIS privacy scan и signing status.
- [ ] Есть rollback artifact/procedure.
- [ ] Release owner явно одобрил публикацию.

Если хотя бы один пункт, влияющий на данные, секреты, установку или lifecycle,
не закрыт, сборка остаётся internal candidate и не маркируется stable.
