<img src="../apps/web/public/brand/iris-mark-backed-dark.svg" width="36" alt="Знак Iris">

<sub>[Документация](index.md) / Окружение</sub>

# Окружение и зависимости

Профили зависимостей описывают назначение среды, а не содержимое случайной
рабочей `.venv`. Пакеты старых экспериментов не должны попадать в установщик.

## Инструменты

| Инструмент | Источник версии | Назначение |
| :--- | :--- | :--- |
| Python | [`.python-version`](../.python-version), `3.12.1` | Ядро и инструменты сборки |
| Node.js | [`.nvmrc`](../.nvmrc), `24.18.0`; npm `11.x` | React/Vite и Tauri CLI |
| Rust | [`rust-toolchain.toml`](../rust-toolchain.toml), `stable` | Оболочка Tauri |
| Unity | [`ProjectVersion.txt`](../apps/avatar-unity/ProjectSettings/ProjectVersion.txt), `2022.3.62f3` | Пересборка аватара |
| FFmpeg / FFprobe | Исполняемые файлы в `PATH` для разработки | Обработка аудио |
| Microsoft C++ Build Tools и WebView2 | Windows-среда разработки Tauri | Сборка и запуск оболочки |
| Docker Desktop | Необязательный внешний компонент | Выполнение команд Coding Agent |

`rust-version = 1.77.2` в Cargo — нижняя граница совместимости, а не закреплённая
версия установленного компилятора. Unity и Docker не нужны для работы над
обычным интерфейсом без этих подсистем.

## Профили Python

| Файл | Назначение |
| :--- | :--- |
| [`runtime.txt`](../requirements/runtime.txt) | Прямые зависимости ядра для установки и упаковки |
| [`dev.txt`](../requirements/dev.txt) | Тесты и измерения |
| [`build.txt`](../requirements/build.txt) | Runtime и PyInstaller |
| [`constraints.txt`](../requirements/constraints.txt) | Ограничения транзитивных версий |
| [`torch-cpu.txt`](../requirements/torch-cpu.txt) | CPU-канал PyTorch |
| [`torch-cu128.txt`](../requirements/torch-cu128.txt) | CUDA-канал PyTorch для отдельного окружения |
| [`stt-cuda.txt`](../requirements/stt-cuda.txt) | Ускорение ONNX STT без смены TTS |
| [`requirements.txt`](../requirements.txt) | Объединённый runtime/dev-профиль |

`constraints.txt` ограничивает выбор версий и сам не устанавливает пакеты.
Не заменяйте профили результатом `pip freeze` из долгоживущей среды.

## Первая установка

В новом клоне, из корня репозитория:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements/torch-cpu.txt
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
npm ci --prefix apps/web
npm ci --prefix apps/desktop
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts/check_python_dependencies.py
.\.venv\Scripts\python.exe -m pip check
```

Копируйте `.env.example` только при отсутствии собственной `.env`.
Файл содержит несекретные параметры; ключи вводятся в приложении.
[Запуск](operations.md#запуск-из-исходников) выполняется через Tauri.

При смене состава зависимостей проверяйте новый профиль в отдельной среде,
сохраняя прежнюю до успешной проверки:

```powershell
py -3.12 -m venv .venv-clean
.\.venv-clean\Scripts\python.exe -m pip install -r requirements/torch-cpu.txt
.\.venv-clean\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-clean\Scripts\python.exe scripts/check_python_dependencies.py
.\.venv-clean\Scripts\python.exe -m pip check
```

## GigaAM ONNX и локальное ускорение STT

Текущий основной STT: `gigaam_onnx`, `v3_rnnt`, FP32, `device=auto`.
Он использует CUDA при совместимом установленном runtime, иначе CPU.
TeraTTSv2 остаётся на CPU. Прежний PyTorch-провайдер доступен как `gigaam`.

Для выбранной development-среды **после** установки основного профиля:

```powershell
.\.venv\Scripts\python.exe -m pip uninstall -y onnxruntime
.\.venv\Scripts\python.exe -m pip install -r requirements/stt-cuda.txt
.\.venv\Scripts\python.exe scripts/check_python_dependencies.py --stt-cuda
.\.venv\Scripts\python.exe -m pip check
```

CPU `onnxruntime` и `onnxruntime-gpu` используют одно имя Python-модуля;
одновременно их не устанавливают. Повторная установка основного профиля
требует заново выбрать один runtime. Профиль закрепляет проверенные версии,
в том числе cuDNN `9.10.2.21` для локальной проверки на GTX 1660 SUPER.

Некоторые пакеты требуют именно distribution `onnxruntime`. Поэтому
`pip check` может сообщать об отсутствии CPU-пакета при рабочем GPU runtime.
Проверка `--stt-cuda` учитывает эту замену; остальные конфликты требуют
отдельного разбора.

Возврат к CPU:

```powershell
.\.venv\Scripts\python.exe -m pip uninstall -y onnxruntime-gpu
.\.venv\Scripts\python.exe -m pip install onnxruntime==1.23.2
```

При необходимости задайте `VOICE_STT_DEVICE=cpu` в `.env`.
Профиль CPU не использует оставшиеся NVIDIA-пакеты.

Веса находятся вне репозитория, в каталоге моделей:
`gigaam-v3-rnnt-onnx/322c3b29492673eb7d0b434bfa9dfb8653e34d02`.
`VOICE_STT_ONNX_MODEL_PATH` выбирает существующую локальную папку.
При отсутствии весов загрузка получает закреплённые FP32 RNNT-файлы;
записи речи наружу не отправляются.

`VOICE_STT_ONNX_THREADS=4` задаёт число потоков для GPU-профиля,
`VOICE_STT_ONNX_CPU_THREADS=8` — для CPU. В `auto` ошибки CUDA-инициализации,
CUDA inference или нехватка памяти допускают переход на CPU с повтором всей
реплики. Явный `cuda` — строгий режим без такого перехода.
Не относящиеся к CUDA ошибки не скрываются повторной обработкой.

## Среда установщика

Обычный запуск `build-desktop-release.ps1` пересоздаёт `build/release-venv`,
ставит `torch-cpu.txt`, затем `build.txt`. PyInstaller использует только эту
среду. Проверка зависимостей отклоняет незаявленные пакеты, включая удалённые
`edge-tts`, `silero-stress`, `supertonic`, `py7zr` и `torchvision`.

Базовая сборка — CPU. CUDA-вариант требует отдельной поставки и проверки.
Qwen ASR/TTS из экспериментальных окружений не входит в основной runtime.

Готовая сборка содержит Python-ядро; пользователю не должны требоваться Python,
Node.js или Rust. Перед публикацией ещё нужно подтвердить:

- доставку WebView2, необходимых системных библиотек и аудиоинструментов;
- загрузку моделей с понятным размером, проверкой целостности и повтором;
- опциональность Docker и отсутствие навязанного GPU-профиля;
- полноту лицензий пакетов, весов и бинарных компонентов;
- воспроизводимость транзитивного графа: прямые pins и constraints не равны
  полному lock-файлу с хешами всех wheels.

См. [условия публикации](release-checklist.md) и [порядок выпуска](release-runbook.md).
