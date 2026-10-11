<img src="../apps/web/public/brand/iris-mark-backed-dark.svg" width="36" alt="Знак Iris">

<sub>[Документация](index.md) / Эксплуатация</sub>

# Запуск, сборка и диагностика

Все команды выполняются из корня репозитория в PowerShell.
Разработка и сборка настольного приложения рассчитаны на Windows 10/11.
Версии инструментов и установка пакетов — в [зависимостях](dependencies.md).
Аппаратные ориентиры и их обоснование — в [системных требованиях](system-requirements.md).

## Запуск из исходников

После подготовки окружения и копирования `.env.example` в `.env`:

```powershell
npm --prefix apps/desktop run dev
```

Tauri запускает Vite и `python -m apps.backend.desktop_entry`, выбирает
случайный локальный порт и токен. Ключи вводятся в
**Настройки → Система → API-ключи**. Для полного выхода используйте **Выйти**
(**Quit** в английском интерфейсе) в области уведомлений Windows или `Ctrl+C`
в терминале запуска. Закрытие главного окна тоже запускает штатное завершение
ядра и аватара; сворачивание окна оставляет приложение работающим.

Безопасный режим запускает ядро без Unity и предварительной загрузки речевых
моделей. Он полезен, когда неисправность необязательной подсистемы мешает запуску.

### Раздельный запуск

Два окна PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --ws websockets-sansio --reload
```

```powershell
npm --prefix apps/web run dev
```

Интерфейс: `http://127.0.0.1:5173`; OpenAPI: `http://127.0.0.1:8000/docs`.
Этот режим подходит для разработки UI и ядра, но не получает ключи из
Credential Manager. Для запросов к пользовательским моделям запускайте Tauri.
Его сервер разработки использует отдельный порт `1420`.
`--ws websockets-sansio` выбирает тот же WebSocket-движок, что управляемое
ядро, и исключает старый legacy-путь Uvicorn/websockets.

## Где находятся данные

При управляемом запуске Tauri задаёт `%LOCALAPPDATA%\NeuroAsist`:

```text
%LOCALAPPDATA%\NeuroAsist\
├── data\neuroasist.sqlite3   история, память, задания и состояние персонажа
├── data\chroma\             перестраиваемый поисковый индекс памяти
├── data\audio\              временные файлы синтезированной речи
├── settings.json            несекретные настройки
├── backups\                 ZIP-снимки данных
├── logs\app.log             журнал ядра
├── models\                  управляемые и локальные модели
├── stt-terms.json            словарь распознавания
└── tts-pronunciations.json   словарь произношения
```

`NEUROASIST_APP_DATA_DIR` меняет корневой каталог. В браузерной разработке
относительные `SQLITE_PATH` и `VOICE_AUDIO_DIR` разрешаются от корня репозитория.

Ключи диалога, Coding Agent и поисковых сервисов — отдельные записи Windows
Credential Manager. Tauri передаёт их ядру через анонимный stdin-канал.
`.env` и унаследованное окружение не принимаются как источники секретов.
Ключи не записываются в `settings.json` или резервные копии.

## Диагностика

| Где смотреть | Что проверять |
| :--- | :--- |
| Настройки → Система → События | Последние ошибки и идентификаторы операций |
| `GET /status` | Версия, доступность базы и наличие ключа LLM |
| `GET /readiness` | Отдельная готовность текста, STT, TTS и живого разговора |
| `GET /diagnostics` | Каталоги данных и состояние моделей |
| `GET /debug/llm/usage` | Токены, кэш, повторные попытки и задержки |
| `logs\app.log` в каталоге данных | Журнал управляемого ядра |

В отчёт включайте версию, шаги воспроизведения, идентификаторы событий и
короткий фрагмент журнала. До отправки проверьте его на личные данные.
Не прикладывайте ключи, полную базу разговоров или записи микрофона.

Если локальный запрос возвращает неожиданный `503`, проверяйте сам HTTP-ответ
с обходом системного прокси. Открытый TCP-порт ещё не доказывает готовность ядра.

## Резервные копии

**Настройки → Система → Резервные копии** создаёт согласованную копию SQLite
и прикладывает `settings.json`. При создании новой копии удаляются снимки
старше `BACKUP_RETENTION_DAYS`; отдельной ежедневной очистки нет.
Создание, список и удаление реализованы; восстановления через интерфейс пока нет.

ZIP содержит только `data/neuroasist.sqlite3` и существующий `settings.json`.
Веса моделей, аудиокэш, журналы, индекс Chroma, `stt-terms.json`,
`tts-pronunciations.json` и файлы рабочих областей Coding Agent не включены.
Пользовательские словари и нужные файлы задач сохраняйте отдельно; индекс
можно перестроить из SQLite. Такая копия не является полным снимком каталога данных.

При проверке резервной копии проверьте целостность ZIP и выполните
`PRAGMA integrity_check` на извлечённой **копии** базы. Создание ZIP само по
себе такую проверку не выполняет. Она не заменяет восстановление на чистой установке.
Не заменяйте базу, пока работает ядро. Поддерживаемая процедура восстановления
остаётся [условием публикации](release-checklist.md).

## Проверки изменений

Для документации:

```powershell
.\.venv\Scripts\python.exe scripts/check_docs.py
```

Для изменений, затрагивающих несколько подсистем:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/desktop run check
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Дополнительные проверки окружения:

```powershell
.\.venv\Scripts\python.exe scripts/check_python_dependencies.py
.\.venv\Scripts\python.exe -m pip check
npm --prefix apps/web audit --omit=dev --audit-level=high
npm --prefix apps/desktop audit --omit=dev --audit-level=high
```

Для GPU-профиля STT используйте `check_python_dependencies.py --stt-cuda`;
оговорка о `pip check` описана в [зависимостях](dependencies.md#gigaam-onnx-и-локальное-ускорение-stt).

### Жизненный цикл ядра

```powershell
.\scripts\smoke_desktop_core.ps1
.\scripts\benchmark-startup.ps1 -Scenario both
```

Первый сценарий использует временные данные и тестовые речевые провайдеры:
проверяет авторизацию и корректную остановку. Второй измеряет готовность
текста и голоса при первом и повторном запуске. Сохраните JSON для сравнения.

### Синтетический длительный прогон

```powershell
.\.venv\Scripts\python.exe scripts/live_conversation_soak.py --duration 300 --cycles 120
.\.venv\Scripts\python.exe scripts/live_conversation_soak.py --release --output artifacts/live-soak.json
```

`--release` запускает одночасовой профиль с ограничением роста RSS;
`--full` — расширенный четырёхчасовой. Это проверка состояний и отмены задач
без микрофона. Для релиза отдельно требуется живой разговор с аватаром.

## Необязательные компоненты

Образ Coding Agent:

```powershell
docker build -t neuroasist-coding:latest -f apps/backend/docker/coding.Dockerfile apps/backend/docker
```

Docker Desktop должен работать. Отсутствие среды делает агент недоступным;
команды не переносятся на хост. Подробнее — [Coding Agent](coding-agent.md).

Пересборка аватара:

В новом клоне собранного аватара нет. Установите Unity 2022.3.62f3 с модулем
Windows Build Support (Mono); без аватара текст и голос работают.

```powershell
$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\2022.3.62f3\Editor\Unity.exe'
npm --prefix apps/desktop run build:avatar
```

Сначала закройте Unity Editor и работающий аватар. Результат:
`apps\avatar-unity\Builds\NeuroAsistAvatar\NeuroAsistAvatar.exe`.

## Кандидат Windows-сборки

После проверок исходников и сборки Unity:

```powershell
.\scripts\build-desktop-release.ps1 -RequireCleanWorktree -ArtifactDirectory artifacts
```

Сценарий создаёт отдельную `build\release-venv`, устанавливает CPU-профиль,
собирает ядро PyInstaller, проверяет упакованное ядро с токеном и ресурсы на
частные данные и удалённые зависимости, собирает NSIS и создаёт SHA-256-манифест.
Временное изменение ресурсов `tauri.conf.json` восстанавливается в `finally`.
Рабочая developer `.venv` не является источником пакетов установщика.

`-SkipDependencyInstall` разрешён при повторе с неизменными профилями
зависимостей. `-ReuseCore` — только для повторения этапа Tauri/NSIS из того же
набора исходников, зависимостей и версии. После их изменения соберите ядро заново.

Отдельная проверка готового ядра:

```powershell
$coreExecutable = 'C:\path\to\neuroasist-core.exe'
.\scripts\smoke_packaged_runtime.ps1 -Executable $coreExecutable
```

Замените путь на фактически собранный файл. Публикация требует
[порядка выпуска](release-runbook.md) и закрытых [условий](release-checklist.md).

## Если что-то не работает

| Симптом | Следующий шаг |
| :--- | :--- |
| Нет текстового ответа | Проверить `/status`, наличие ключа и события LLM |
| Голос не готов | Проверить `/readiness`, модели, разрешение микрофона и FFmpeg |
| В конкретном приложении нет звука | Проверить его устройство вывода и громкость в микшере Windows |
| Фоновый исполнитель остановился | Найти `backend.worker_failed` и причину повторного запуска |
| Не запускается Unity | Запустить безопасный режим, проверить состояние аватара и журнал сборки |
| Настройки не сохраняются | Проверить доступ к файлу; прежнее опубликованное состояние остаётся действующим |
| Ошибка SQLite | Завершить Iris, сохранить базу и резервные копии, исследовать отдельную копию |

---

[Окружение](dependencies.md) · [Выпуск](release-runbook.md) · [Безопасность](../SECURITY.md)
