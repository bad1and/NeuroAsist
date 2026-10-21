# Зависимости Iris — разбор перед кандидатом

Дата: 20 октября 2026 года. Область: Windows x64, CPU release-среда,
управляемые модели. Это проверка исходников и окружения; фактический состав
нового EXE проверяется на третьем этапе.

## Обновления

| Компонент | Было | Стало |
| :--- | :--- | :--- |
| FastAPI / Starlette | 0.116.0 / 0.46.2 | 0.135.2 / 1.3.1 |
| python-multipart | 0.0.20 | 0.0.32 |
| aiohttp / AnyIO | 3.14.1 / 4.14.1 | 3.14.4 / 4.14.2 |
| fsspec / Hydra | 2026.4.0 / 1.3.2 | 2026.6.0 / 1.3.7 |
| multidict / yarl | 6.7.1 / 1.24.2 | 6.9.1 / 1.25.1 |
| urllib3 / setuptools | 2.7.0 / 78.1.0 | 2.8.0 / 78.1.1 |
| sentence-transformers | 3.4.1 | 5.6.0 |
| Rust event-listener | 5.4.1 | 5.4.2 |
| pip в build-профиле | Не закреплён; venv ставил 23.2.1 | 26.2.2 |

Выбраны совместимые исправленные версии; это не обновление всех пакетов до
последних major. FastAPI допускает выбранную Starlette согласно
[метаданным пакета](https://pypi.org/pypi/fastapi/0.135.2/json).
Исправления multipart и Range сверены с
[advisory загрузок](https://github.com/Kludex/starlette/security/advisories/GHSA-2c2j-9gv5-cj73)
и [advisory Range](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8).

## Оставшиеся совпадения

OSV: 636 запросов по установленной build-среде и всему Cargo.lock;
16 совпавших версий, 53 ID. ID включают GHSA/PYSEC-алиасы и Rust maintenance
warnings; это не 53 независимых доступных атаки. npm root/Web/Desktop:
0 опубликованных совпадений на дату проверки.

Поимённый список всех 53 ID, условия и ссылки на источники:
[машиночитаемые решения](security-dependency-decisions.json).

| Группа | Решение и граница |
| :--- | :--- |
| Chroma | Используется встроенный PersistentClient, коллекции с `embedding_function=None` и готовыми векторами. Chroma HTTP server, tenant RBAC и удалённая конфигурация embedding-функций не публикуются. Серверные пути из advisory в этом профиле недоступны. |
| OAuthlib | Транзитивная клиентская зависимость; Iris не предоставляет OAuth/PKCE/JSONP-сервер из этих advisory. |
| ONNX 1.19.1 | GigaAM требует ветку 1.19. Обновление до 1.23.2 отвергнуто резолвером; требования не обходились. Инференс Iris использует ONNX Runtime, без Python ONNX hub/checker/converter/export/save API. При добавлении этих функций разбор повторить. |
| Transformers 4.57.3 | Нет Trainer, LightGlue, custom_generate и сохранения tokenizer/chat templates. TeraTTS использует намеренно доверенный закреплённый код, проверяемый Model Manager. Исключение условно: произвольные и изменённые конфигурации моделей его отменяют. |
| Torch 2.11 CPU | Advisory касается компиляции через `torch.jit.script`; Iris загружает готовый проверенный Silero JIT. Произвольный пользовательский код/модель этим решением не одобряется. |
| setuptools | Остаточная находка касается macOS Unicode-коллизий при сборке sdist. Этот разбор относится к Windows. |
| glib, proc-macro-error, zbus/zvariant | Отсутствуют в выбранном Windows-графе normal/build. Linux/macOS требуют своего разбора. |
| unic crates | Присутствуют в Tauri-графе; advisory фиксируют отсутствие сопровождения. Оставлены как явно учтённый технический долг с повторной проверкой upstream перед выпуском. |

Основания ограничены фактическими путями Iris: `semantic/chroma_index.py`,
`semantic/embedding.py`, `voice/teratts_provider.py`, `voice/gigaam_onnx.py`,
`voice/input.py`, `model_manager/service.py` и авторизацией в `backend/main.py`.
Проверка не объявляет эти библиотеки безопасными для любого применения.

## Воспроизведение

```powershell
.\build\release-venv-stage2\Scripts\python.exe scripts/check_python_dependencies.py --profile runtime --profile build --strict
.\build\release-venv-stage2\Scripts\python.exe -m pip check
.\build\release-venv-stage2\Scripts\python.exe scripts/audit_dependencies.py --output output/release-stage2-20261020/osv-installed.json --decisions Docs/security-dependency-decisions.json
npm --prefix apps/web audit
npm --prefix apps/desktop audit
npm audit
```

Сканер сохраняет хеши требований и lock-файла, обрабатывает продолжения OSV
и отдельно отмечает Cargo-пакеты Windows. Сетевой сбой завершает проверку
ошибкой. Флаг `--decisions` отклоняет новые неразобранные ID и устаревшие хеши
требований. Успешное завершение сканера означает получение снимка, а не отсутствие
находок или автоматическое одобрение выпуска.

Логи и полные ответы OSV находятся в `output/release-stage2-20261020/`.
Перед выпуском повторить сканирование на окончательной среде, сверить новые ID,
состав EXE и условия этого разбора. Права поставки учитываются отдельно в
[перечне материалов](../THIRD_PARTY_ASSETS.md).
