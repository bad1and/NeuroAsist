<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="Docs/media/readme/header.ru.dark.png">
    <img src="Docs/media/readme/header.ru.light.png" width="900" alt="Ирис — помощник, с которым можно поговорить. По краям — акварельные ирисы">
  </picture>

# Ирис

Голосовой помощник для Windows, с которым можно обсудить идею, разобрать задачу или просто поговорить.<br>
Ирис помнит важное из бесед; рядом с окном диалога можно разместить аватар.

**Русский** · [English](README.en.md) · [Документация](Docs/index.md)

[![Версия исходников](https://img.shields.io/badge/version-0.9.1-695B86?style=flat-square)](VERSION) · [Apache 2.0](LICENSE)

[Возможности](#возможности) · [Интерфейс](#интерфейс) · [Требования](#системные-требования) · [Запуск](#запуск) · [Данные](#данные) · [Разработка](#разработка)

</div>

[![Обзор Iris: начало разговора, последняя беседа, память и состояние системы](Docs/media/readme/overview.png)](Docs/media/readme/overview.png)

<sub>Главный экран</sub>

Распознавание и озвучивание речи работают на компьютере. За ответы отвечает внешняя модель: для разговора нужны интернет и API-ключ выбранного сервиса.

Пока Ирис запускается из исходников. [Статус выпуска](Docs/MILESTONES.md).

## Возможности

**Разговор.** С Ирис можно говорить голосом или переписываться. В голосовом режиме она определяет конец реплики; ответ можно перебить. [О голосовом разговоре](Docs/live-conversation.md).

**Память.** Ирис сохраняет важные сведения из бесед. Записи можно прочитать, исправить или удалить в разделе памяти. [Как работает память](Docs/chroma-memory.md).

**Планы и документы.** В памяти доступны планы и напоминания, поиск и сортировка.
К беседе можно прикрепить TXT, MD или текстовый PDF и проверить источники ответа.
Документы хранятся временно; в новых записях истории остаются ответ и сведения
об источниках. [Руководство](Docs/user-guide.md).

**Первый запуск и навигация.** Мастер помогает подготовить разговор, а **Ctrl+K**
ищет по истории, памяти, планам и настройкам. Можно начать с текста и подключить голос позже.

**Поиск.** Если нужно проверить информацию или найти новости, Ирис может обратиться к поиску. Результаты и источники остаются в истории. Уведомления о поиске по умолчанию выключены. [Поиск и новости](Docs/awareness.md).

**Аватар.** Необязательный Unity-аватар можно разместить на рабочем столе или внутри окна диалога. Он сопровождает речь движением губ и жестами. [Настройка аватара](apps/avatar-unity/README.md).

**Coding Agent.** Отдельный агент работает с задачами по коду в Docker. Изменения можно просмотреть перед переносом в проект. Для него нужны Docker и собственный API-ключ. [Настройка и границы доступа](Docs/coding-agent.md).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="Docs/media/readme/interface.ru.dark.png">
    <img src="Docs/media/readme/interface.ru.light.png" width="900" alt="Как выглядит Ирис">
  </picture>
</p>

## Интерфейс

### Диалог

[![Диалог Iris в приложении Windows: Unity-аватар, субтитры ответа, поле сообщения и управление голосом](Docs/media/readme/dialogue.png)](Docs/media/readme/dialogue.png)

Здесь можно писать, включать голосовой разговор и читать субтитры ответа. Аватар можно отключить.

### Память

[![Память Iris: подготовленные записи о ночных правках, коротких ответах и планах](Docs/media/readme/memory.png)](Docs/media/readme/memory.png)

У записей из бесед можно посмотреть источник — сообщение, из которого Ирис их запомнила.

<details>
<summary>История</summary>

[![История Iris: список разговоров и сообщения выбранного диалога](Docs/media/readme/history.png)](Docs/media/readme/history.png)

Список бесед и поиск по сообщениям.

</details>

<details>
<summary>Состояние</summary>

[![Состояние Iris: настроение и состояние отношений](Docs/media/readme/state.png)](Docs/media/readme/state.png)

Настроение Ирис и состояние отношений с собеседником.

</details>

<details>
<summary>Настройки голоса</summary>

[![Настройки голоса Iris: язык, голос и параметры воспроизведения](Docs/media/readme/voice-settings.png)](Docs/media/readme/voice-settings.png)

Микрофон и устройство вывода выбираются отдельно, в разделе устройств.

</details>

<details>
<summary>Coding Agent</summary>

[![Coding Agent: раздел задач без запущенных заданий](Docs/media/readme/coding.png)](Docs/media/readme/coding.png)

Задачи агента, изменения в файлах и журнал выполнения. На снимке задач ещё нет.

</details>

<sub>Снимки сделаны в отдельном профиле с подготовленными примерами разговоров и памяти.</sub>

## Системные требования

Для текущего запуска из исходников с локальным голосом и внешней моделью диалога:

| Компонент | Минимальные — расчётный ориентир | Рекомендованные |
| :--- | :--- | :--- |
| ОС | Windows 10 22H2, x64 | Windows 11, x64 |
| Процессор | 4 ядра / 8 потоков, поддержка AVX2 | AMD Ryzen 7 5700X, 8 ядер / 16 потоков |
| ОЗУ | 8 ГБ; перед запуском свободно около 5 ГиБ | 16 ГБ; 32 ГБ при работе вместе с Docker, Unity Editor или тяжёлыми приложениями |
| Графика | Встроенная для интерфейса; речь может работать на CPU без дискретной карты | NVIDIA GTX 1660 SUPER, 6 ГБ видеопамяти — ориентир для аватара и необязательного CUDA STT |
| Свободное место | 20 ГиБ для исходников, зависимостей, моделей и временных файлов | 30 ГиБ на SSD; инструменты сборки, Unity и Docker требуют отдельного места |
| Подключение и звук | Интернет и API-ключ модели; микрофон и наушники или колонки для голоса | Стабильный интернет, микрофон и наушники для меньшего акустического эха |

Минимум рассчитан для голосового режима без аватара и Docker; на компьютере с 8 ГБ он ещё не испытан. Речевые модели в отдельном CPU-прогоне заняли около 3,1 ГиБ ОЗУ, веса — около 1,93 ГиБ на диске. Рекомендация 16 ГБ оставляет запас для Windows и интерфейса. Видеокарта не обязательна для голоса; ускорение требует [отдельного ONNX CUDA-профиля](Docs/dependencies.md#gigaam-onnx-и-локальное-ускорение-stt).

**Эталон запуска Iris:** компьютер разработчика — Ryzen 7 5700X, **32 ГБ ОЗУ**, GTX 1660 SUPER **6 ГБ**, Windows 11 Pro x64. Характеристики сверены 12 октября 2026 года. Рекомендация по ОЗУ снижена до 16 ГБ по расчёту; это не отдельное испытание на машине с 16 ГБ. [Расчёт, условия и требования дополнительных компонентов](Docs/system-requirements.md).

## Запуск

Для запуска из исходников понадобятся Git, **Python 3.12**, **Node.js 24 / npm 11**. Аудио декодируется через поставляемый PyAV; глобальные FFmpeg/FFprobe не требуются. Для оболочки Tauri нужны текущий stable Rust из `rust-toolchain.toml`, Microsoft C++ Build Tools с компонентом **Desktop development with C++** и WebView2 Runtime. Значение Rust 1.77.2 в Cargo задаёт нижнюю границу, а не версию для установки. [Подготовка Windows для Tauri](https://v2.tauri.app/start/prerequisites/).

### Установить зависимости

```powershell
git clone https://github.com/bad1and/NeuroAsist.git Iris
cd Iris

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements/torch-cpu.txt
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

npm ci
npm ci --prefix apps/web
npm ci --prefix apps/desktop

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Это базовый CPU-профиль. Необязательное ускорение STT подключается **после** него по инструкции ниже. [Подробнее о зависимостях](Docs/dependencies.md).

### Открыть Ирис

```powershell
npm --prefix apps/desktop run dev
```

Оболочка сама запускает интерфейс и локальное ядро. В **Настройки → Система → API-ключи** сохраните ключ модели диалога. Ключи хранятся в Windows Credential Manager; `.env` предназначен для несекретных параметров.

Для первого разговора достаточно текста. Чтобы включить голос, дождитесь загрузки речевых моделей и выберите микрофон и устройство вывода. Для скачивания моделей понадобятся интернет и место на диске.

Для полного выхода закройте главное окно или выберите **Выйти** в меню значка Ирис в области уведомлений Windows (**Quit** в английском интерфейсе). Сворачивание окна оставляет приложение работающим. [Первый запуск и повседневная работа](Docs/user-guide.md).

<details>
<summary>CUDA — ускорение распознавания речи</summary>

Видеокарта NVIDIA может ускорить текущий GigaAM ONNX. После установки базового профиля замените CPU ONNX Runtime на GPU-вариант:

```powershell
.\.venv\Scripts\python.exe -m pip uninstall -y onnxruntime
.\.venv\Scripts\python.exe -m pip install -r requirements/stt-cuda.txt
.\.venv\Scripts\python.exe scripts/check_python_dependencies.py --stt-cuda
```

Оставьте `VOICE_STT_DEVICE=auto` в `.env` для выбора CUDA с резервом CPU. Нужен совместимый драйвер NVIDIA; CPU и GPU ONNX Runtime одновременно не устанавливаются. PyTorch и TeraTTSv2 остаются на CPU. Профиль `torch-cu128.txt` относится к PyTorch и сам по себе не ускоряет GigaAM ONNX. [Проверка и возврат к CPU](Docs/dependencies.md#gigaam-onnx-и-локальное-ускорение-stt).

</details>

<details>
<summary>Unity — пересборка аватара</summary>

Аватар необязателен. В новом клоне готового исполняемого файла нет: для его первой сборки и последующих пересборок нужны Unity 2022.3.62f3 и модуль **Windows Build Support (Mono)**:

```powershell
$env:NEUROASIST_UNITY_EDITOR = 'C:\Program Files\Unity\Hub\Editor\2022.3.62f3\Editor\Unity.exe'
npm --prefix apps/desktop run build:avatar
```

[Сборка и настройка Unity-аватара](apps/avatar-unity/README.md).

После сборки Tauri найдёт аватар автоматически. Без него текст и голос доступны.

</details>

<details>
<summary>Docker — среда для Coding Agent</summary>

Запустите Docker Desktop. Образ можно подготовить из Coding Agent; для разработки доступна команда:

```powershell
docker build -t neuroasist-coding:1.0.0 -f apps/backend/docker/coding.Dockerfile apps/backend/docker
```

Сохраните отдельный Coding API-ключ в настройках приложения и включите агента. Ключ диалоговой модели вместо него не используется. [Полная инструкция](Docs/coding-agent.md).

</details>

<details>
<summary>Браузерный режим — разработка интерфейса и ядра</summary>

В двух окнах PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --ws websockets-sansio --reload
```

```powershell
npm --prefix apps/web run dev
```

Интерфейс — `http://127.0.0.1:5173`, описание API — `http://127.0.0.1:8000/docs`.

Браузерный режим не получает ключи из Windows Credential Manager. Для запросов к модели запускайте приложение через Tauri.

</details>

Если приложение не запускается или не слышно голос, начните с [диагностики](Docs/operations.md#диагностика).

## Данные

История, память и настройки хранятся на компьютере. При запуске через Tauri — в `%LOCALAPPDATA%\NeuroAsist`. Запись с микрофона по умолчанию не сохраняется.

Для ответа модель получает текст запроса и выбранный контекст беседы. Поиск обращается к внешним источникам. [Подробнее о данных](PRIVACY.md).

Удаление записи памяти и исходного сообщения — разные действия. В настройках доступны создание, импорт, экспорт и восстановление резервных копий. Desktop-оболочка останавливает ядро перед заменой данных и сохраняет предыдущую копию. Ирис не предоставляет общего управления рабочим столом, а Coding Agent работает в своей изолированной среде.

[Безопасность](SECURITY.md) · [Текущий статус проекта](Docs/MILESTONES.md) · [Условия выпуска](Docs/release-checklist.md)

## Разработка

| Каталог | Что внутри |
| :--- | :--- |
| `apps/web` | Интерфейс React |
| `apps/backend` | Диалог, голос, память и локальное API |
| `apps/desktop` | Оболочка Windows на Tauri |
| `apps/avatar-unity` | Необязательный Unity-аватар |
| `apps/protocol` | Общие контракты персонажа и аватара |
| `Docs`, `scripts`, `tests` | Документация, инструменты и проверки |

Основные проверки из корня репозитория:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/desktop run check
.\.venv\Scripts\python.exe scripts/check_docs.py
```

[Документация](Docs/index.md) · [Архитектура](Docs/architecture.md) · [Участие в разработке](CONTRIBUTING.md) · [Дизайн Ирис](design.md)

Версию задаёт `VERSION`. Порядок сборки установщика и проверки перед публикацией описаны в [эксплуатации](Docs/operations.md) и [руководстве выпуска](Docs/release-runbook.md).

<p align="center">
  <a href="Docs/media/readme/poster-less-noise.png"><img src="Docs/media/readme/poster-less-noise.png" width="260" alt="Постер «Меньше шума — больше мысли»"></a>
  <a href="Docs/media/readme/poster-always-with-you.png"><img src="Docs/media/readme/poster-always-with-you.png" width="260" alt="Футуристический постер IRIS — Always with you"></a>
  <a href="Docs/media/readme/poster-assistant-project.png"><img src="Docs/media/readme/poster-assistant-project.png" width="260" alt="Постер Assistant Project: Iris"></a>
</p>

---

Код распространяется по [Apache 2.0](LICENSE). У моделей, аватара и других сторонних материалов свои условия: [состав и происхождение](THIRD_PARTY_ASSETS.md).

[Документация](Docs/index.md) · [История изменений](CHANGELOG.md) · [English](README.en.md) · [К началу](#ирис)
