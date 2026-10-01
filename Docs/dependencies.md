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

### GigaAM ONNX и локальное ускорение STT

Основной STT — `gigaam_onnx`, модель `v3_rnnt`, FP32. Базовый runtime включает
`onnx-asr==0.12.0` и CPU ONNX Runtime; `VOICE_STT_DEVICE=auto` выбирает CUDA при
наличии совместимого runtime, иначе CPU. TeraTTS/PyTorch остаются на CPU.
ONNX-пакет включён в оба PyInstaller build entrypoints; CUDA-библиотеки
в базовую CPU-сборку не добавлены.

Для Windows development после установки основного профиля:

```powershell
.\.venv\Scripts\python.exe -m pip uninstall -y onnxruntime
.\.venv\Scripts\python.exe -m pip install -r requirements/stt-cuda.txt
.\.venv\Scripts\python.exe scripts/check_python_dependencies.py --stt-cuda
.\.venv\Scripts\python.exe -m pip check
```

Не устанавливать CPU `onnxruntime` и `onnxruntime-gpu` одновременно: они
используют один Python module. После повторной установки основного профиля
нужно заново выбрать один runtime. Опциональный CUDA-профиль фиксирует
проверенные версии, включая cuDNN 9.10.2.21 для GTX 1660 SUPER.
Возврат к CPU: удалить `onnxruntime-gpu`, установить `onnxruntime==1.23.2`
и задать `VOICE_STT_DEVICE=cpu`. NVIDIA wheels можно оставить до отдельной
очистки окружения; они не используются CPU-режимом.
Некоторые зависимости декларируют именно имя CPU distribution `onnxruntime`:
`pip check` сообщает его отсутствие даже при рабочем GPU runtime.
`check_python_dependencies.py --stt-cuda` учитывает эту замену при обходе графа;
остальные сообщения `pip check` требуют отдельной проверки окружения.

Модель хранится вне репозитория: `%LOCALAPPDATA%/NeuroAsist/models/` /
`gigaam-v3-rnnt-onnx/322c3b29492673eb7d0b434bfa9dfb8653e34d02`.
`VOICE_STT_ONNX_MODEL_PATH` позволяет выбрать готовую локальную папку.
При отсутствии файлов preload скачивает только FP32 RNNT-файлы по закреплённой
Hugging Face revision. Это загрузка весов, записи речи не передаются.
Первое включение микрофона использует существующий readiness/loading flow.

Настройки: `VOICE_STT_ONNX_THREADS=4` для CUDA preprocessing/CPU work и
`VOICE_STT_ONNX_CPU_THREADS=8` для CPU-сессий. При ошибке инициализации CUDA
или CUDA inference/OOM режим `auto` загружает CPU-модель и повторяет целую
реплику; выбранное устройство и причина перехода доступны в STT metadata.
Явное `VOICE_STT_DEVICE=cuda` означает строгий GPU-режим без CPU-перехода.
Не относящиеся к CUDA ошибки inference не скрываются повторным запуском.
Прежний PyTorch-провайдер доступен через `VOICE_STT_PROVIDER=gigaam`.

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
- ключи DeepSeek и Coding API не включать в installer, `.env` или конфигурацию.
  Пользователь вводит их в **Настройки → Система → API-ключи**, после чего Tauri
  хранит две отдельные записи в Windows Credential Manager;
- GPU-вариант выпускать отдельным подписанным add-on или отдельным installer.
  CPU core всегда должен запускаться сам, а add-on — устанавливаться в
  версионированный каталог после проверки NVIDIA driver, CUDA/CTranslate2 и
  пробного inference. При любой ошибке приложение возвращается на CPU.

Перед публикацией direct profiles следует компилировать в Windows x64 lock с
SHA-256 для всех wheels (или собирать закрытый wheelhouse), а затем устанавливать
release-среду с `--require-hashes`. Git-зависимость GigaAM лучше заранее собрать
в собственный версионированный wheel: commit уже закреплён, но wheel и его hash
сделают сборку воспроизводимой и независимой от доступности GitHub.
