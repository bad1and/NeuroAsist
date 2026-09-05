# Python-зависимости и release-среда

## Профили

Зависимости разделены по назначению:

- `requirements/runtime.txt` — прямые зависимости Python-sidecar, которые
  попадают в Windows installer;
- `requirements/dev.txt` — тесты и локальные benchmark-инструменты;
- `requirements/build.txt` — runtime плюс PyInstaller;
- `requirements/constraints.txt` — проверенные версии транзитивного графа без
  самостоятельной установки пакетов;
- `requirements/torch-cpu.txt` и `requirements/torch-cu128.txt` — явный выбор
  PyTorch wheel channel до установки основного профиля;
- корневой `requirements.txt` — удобный объединённый профиль для разработки.

В профилях фиксируются прямые зависимости, а constraints удерживают проверенные
транзитивные версии. Переносить результат `pip freeze` из рабочей `.venv`
нельзя. Долгоживущее окружение сохраняет пакеты удалённых прототипов даже после
обновления `requirements.txt`.

## Чистая разработческая среда

Если состав зависимостей изменился, надёжнее пересоздать `.venv`, чем удалять
пакеты вручную:

```powershell
deactivate 2>$null
Remove-Item -LiteralPath .venv -Recurse -Force
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\check_python_dependencies.py
.\.venv\Scripts\python.exe -m pip check
```

Удаление `.venv` не затрагивает исходники или пользовательские данные Iris.

## Release-сборка

`scripts/build-desktop-release.ps1` на каждом обычном запуске пересоздаёт
`build/release-venv`, сначала устанавливает `requirements/torch-cpu.txt`, затем
`requirements/build.txt`. PyInstaller запускается только
из этого окружения, а dependency check отклоняет любой незаявленный пакет.
Поэтому старые `edge-tts`, `silero`, `silero-stress`,
`supertonic`, `py7zr`, `torchvision` или другие локальные эксперименты не могут
случайно попасть в sidecar.

`-SkipDependencyInstall` допустим только для повтора сборки из уже созданного
`build/release-venv` при неизменных manifests. `-ReuseCore` дополнительно требует
неизменные исходники и версию.

Базовый installer остаётся CPU-only. Экспериментальные Qwen ASR/TTS окружения
из benchmark-скриптов не входят в Iris 1.0. CUDA runtime следует выпускать как
отдельно тестируемый installer/add-on: его нельзя собирать из developer `.venv`
или добавлять в CPU-sidecar постфактум.

## Граница Windows installer

Пользователю готовой сборки не нужны Python, Node или Rust: PyInstaller
включает интерпретатор и runtime-пакеты в `core`, а Tauri/NSIS доставляет этот
каталог вместе с frontend и Unity renderer. На машине сборки эти инструменты
нужны, на машине пользователя — нет.

До публичной версии остаются отдельные решения по системным компонентам:

- включить WebView2 bootstrapper или offline runtime в NSIS-конфигурацию;
- либо положить совместимые `ffmpeg.exe`/`ffprobe.exe` в resources и запускать
  их по абсолютному resource path, либо убрать последний subprocess-fallback;
- проверить наличие Microsoft Visual C++ Runtime, необходимого Windows wheel
  CTranslate2, и доставлять redistributable только по лицензированному сценарию;
- модели GigaAM/TeraTTS/Smart Turn не смешивать с Python-пакетами: скачивать их
  отдельно по versioned manifest, показывать размер, проверять SHA-256 и уметь
  продолжать/повторять загрузку;
- Docker Desktop оставить опциональной внешней предпосылкой Coding Agent.
  Установщик Iris должен определить его наличие и объяснить включение функции,
  но не принимать за пользователя отдельную лицензию Docker и не навязывать
  WSL/reboot всем пользователям;
- GPU-вариант выпускать отдельным подписанным add-on или отдельным installer.
  CPU core всегда должен запускаться сам, а add-on — устанавливаться в
  версионированный каталог после проверки NVIDIA driver, CUDA/CTranslate2 и
  пробного inference. При любой ошибке приложение возвращается на CPU.

Перед публикацией direct profiles следует компилировать в Windows x64 lock с
SHA-256 для всех wheels (или собирать закрытый wheelhouse), а затем устанавливать
release-среду с `--require-hashes`. Git-зависимость GigaAM лучше заранее собрать
в собственный версионированный wheel: commit уже закреплён, но wheel и его hash
сделают сборку воспроизводимой и независимой от доступности GitHub.
