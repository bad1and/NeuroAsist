# Neuro‑VTuber Assistant Blueprint

**Назначение файла:** это самодостаточный проектный blueprint, который можно загрузить в новый чат и продолжить разработку без потери контекста.

## Контекст проекта и вводные

Проект делается для себя, но с возможностью перерасти в стартап‑продукт, который можно продвигать или продавать. Нужен рабочий MVP с архитектурой, которую можно расширять. Главный ранний приоритет: корректная базовая работа голосового ассистента: пользователь говорит, STT распознает речь, текст уходит через LLM API, ответ возвращается, озвучивается через TTS и синхронизируется с 3D‑моделью.

Текущая платформа: Windows 10/11. В будущем возможна поддержка разных ПК, но не в MVP. Железо: i9‑11900K, 32 GB RAM, RTX 3080 10 GB. Несмотря на наличие видеокарты, LLM лучше использовать через облачные API, чтобы не нагружать GPU, который может понадобиться для 3D‑рендера и других задач.

Разработчик имеет средний уровень Python, небольшой опыт с FastAPI, Docker, Kubernetes и минимальный опыт с LLM API. Проект может делаться в одиночку или вдвоем, жестких дедлайнов нет.

Основной LLM для MVP: DeepSeek V4 Flash через API. Архитектура остается провайдер-независимой, чтобы позже можно было добавить Gemini, OpenAI, Anthropic, Ollama или LM Studio без изменения бизнес-логики. Ключевой принцип: провайдер‑независимая архитектура. Персонаж и dev‑agent должны использовать разные модели/роли, чтобы не нагружать одну модель и можно было подбирать модель под задачу.

Dev‑agent добавляется только после того, как основной голосовой персонаж будет работать стабильно. В идеале dev‑agent должен развиться до аналога Codex/Claude Code/Cursor Agent: читать файлы, писать код, запускать тесты, показывать diff, спрашивать подтверждение, вести лог действий.

Web UI планируется со второй версии. Он должен быть локальным и показывать чат, задачи, логи, статусы агентов, ошибки, результаты, файлы, настройки провайдеров, личности и sandbox.

Для доступа к ПК в MVP лучше не давать никаких опасных прав. Позже — работа в песочнице, project folder, Docker, подтверждение действий, diff и logs. Доступ к экрану и управление мышью/клавиатурой — только в далеком будущем.

---

# 1. Краткое резюме идеи проекта

Цель — сделать локального AI‑персонажа для ПК: 3D‑VTuber‑ассистента, с которым можно общаться голосом и текстом. На первом этапе он должен стабильно выполнять базовый цикл:

```text
пользователь говорит → STT распознает речь → LLM формирует ответ → TTS озвучивает → 3D‑модель двигает губами/эмоциями
```

Дальше система должна вырасти в мультиагентную платформу:

1. **Character Agent** — личность, общение, юмор, голос, эмоции, маршрутизация задач.
2. **Dev Agent** — агент‑разработчик в стиле Codex/Claude Code/Cursor Agent: пишет код, меняет файлы, запускает тесты, показывает diff, работает в sandbox.
3. **Web UI** — локальная панель управления задачами, логами, настройками, API‑провайдерами, личностями и агентами.
4. **Sandbox / Desktop Context** — контролируемый доступ к проектной папке, командам, скриншотам и позже к экрану/браузеру.

Главный принцип архитектуры: **не строить всё вокруг одного LLM API**. Нужен слой абстракции, чтобы сегодня использовать Mistral/DeepSeek/Gemini, завтра OpenAI/Anthropic, потом локальные модели через Ollama.

---

# 2. Рекомендуемая архитектура высокого уровня

Для этого проекта лучший путь — **модульный монолит на Python + отдельный frontend**.

Не микросервисы на старте. Не Kubernetes. Не enterprise‑зоопарк. Иначе проект утонет в инфраструктуре раньше, чем персонаж скажет первую токсичную шутку.

```text
┌──────────────────────────────────────────────────────────────┐
│                         Web UI                               │
│  React/TypeScript: чат, задачи, логи, настройки, агенты       │
└───────────────────────────▲──────────────────────────────────┘
                            │ REST/WebSocket
┌───────────────────────────┴──────────────────────────────────┐
│                    Python Backend / Core API                  │
│                      FastAPI + WebSocket                      │
│                                                              │
│  ┌────────────────────┐     ┌─────────────────────────────┐  │
│  │ Character Agent     │────▶│ Task Router / Orchestrator  │  │
│  └─────────▲──────────┘     └──────────────▲──────────────┘  │
│            │                               │                 │
│  ┌─────────┴──────────┐     ┌──────────────┴──────────────┐  │
│  │ Voice Pipeline      │     │ Dev Agent                   │  │
│  │ STT/TTS/VAD         │     │ code/read/write/test/diff   │  │
│  └─────────▲──────────┘     └──────────────▲──────────────┘  │
│            │                               │                 │
│  ┌─────────┴──────────┐     ┌──────────────┴──────────────┐  │
│  │ Avatar Bridge       │     │ Sandbox Manager             │  │
│  │ VRM/VTS/Unity       │     │ Docker/project folder       │  │
│  └────────────────────┘     └─────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ LLM Provider Layer: OpenAI/Gemini/Mistral/DeepSeek/etc │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Storage: SQLite/Postgres, logs, memory, prompts, tasks │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

Почему так:

- быстро получить работающий цикл;
- не привязаться к одному API;
- оставить возможность добавить dev‑агента;
- не пустить LLM сразу во весь ПК;
- сделать систему расширяемой, но не чрезмерно сложной.

Python подходит для backend, LLM‑оркестрации, STT/TTS, задач, sandbox‑управления. Web UI лучше делать на TypeScript/React. 3D‑часть лучше не писать с нуля на Python.

---

# 3. Список основных модулей системы

## Core backend

Отвечает за API, состояние приложения, WebSocket‑события, настройки.

```text
core/
  app.py
  config.py
  events.py
  dependency_container.py
```

## LLM provider layer

Единый интерфейс для всех моделей.

```text
llm/
  base.py
  messages.py
  registry.py
  providers/
    openai_provider.py
    mistral_provider.py
    deepseek_provider.py
    gemini_provider.py
    anthropic_provider.py
    ollama_provider.py
```

## Agents

```text
agents/
  character_agent/
    agent.py
    prompts.py
    personality.py
    router.py
  dev_agent/
    agent.py
    planner.py
    tools.py
    patcher.py
    tester.py
  base_agent.py
```

## Voice pipeline

```text
voice/
  stt/
    base.py
    whisper_local.py
    cloud_stt.py
  tts/
    base.py
    edge_tts.py
    elevenlabs_tts.py
    piper_tts.py
  vad.py
  audio_io.py
```

## Avatar bridge

```text
avatar/
  base.py
  vtube_studio.py
  unity_bridge.py
  vrm_bridge.py
  emotion_mapper.py
  lipsync.py
```

## Task system

```text
tasks/
  models.py
  queue.py
  runner.py
  status.py
  event_bus.py
```

## Sandbox

```text
sandbox/
  base.py
  local_project_sandbox.py
  docker_sandbox.py
  command_policy.py
  file_policy.py
  approvals.py
  snapshots.py
```

## Storage

```text
storage/
  db.py
  models.py
  repositories/
    tasks_repo.py
    messages_repo.py
    memory_repo.py
    settings_repo.py
    logs_repo.py
```

---

# 4. Схема взаимодействия агентов в текстовом виде

## Базовый диалог

```text
User voice/text
  ↓
Input Gateway
  ↓
STT, если голос
  ↓
Character Agent
  ↓
LLM Provider
  ↓
Response
  ↓
TTS
  ↓
Avatar Bridge
  ↓
3D model speaks + reacts
```

## Запрос на разработку

```text
User: "Сделай калькулятор на Python"
  ↓
Character Agent:
  - отвечает в стиле персонажа
  - определяет intent = coding_task
  - формирует структурированную задачу
  ↓
Task Router
  ↓
Dev Agent:
  - уточняет требования, если нужно
  - строит план
  - создает файлы
  - запускает тесты
  - исправляет ошибки
  - формирует отчет
  ↓
Sandbox Manager:
  - разрешает/запрещает команды
  - логирует действия
  - делает snapshots
  ↓
Web UI:
  - показывает статус
  - показывает diff
  - дает approve/reject
  ↓
Character Agent:
  - пересказывает результат пользователю в стиле персонажа
```

Главная мысль: **Character Agent не должен сам писать код в файловую систему**. Он общается, маршрутизирует и объясняет. Кодом занимается Dev Agent через controlled tools.

---

# 5. Рекомендуемый технологический стек

| Часть | Рекомендация для MVP | Почему |
|---|---|---|
| Backend | Python + FastAPI | Быстро, удобно для LLM/STT/TTS, WebSocket, API |
| Frontend | React + TypeScript + Vite | Быстрее и проще, чем Next.js для локальной панели |
| Desktop app wrapper | Пока не нужен | Сначала localhost web UI |
| DB | SQLite + SQLAlchemy/Alembic | Достаточно для MVP, потом можно мигрировать на Postgres |
| Очередь задач | asyncio.Queue / SQLite task queue | Redis/Celery позже |
| LLM слой | Своя абстракция + LiteLLM как опция | Своя логика важна, LiteLLM может помочь с провайдерами |
| STT | faster-whisper | Основной STT для MVP: бесплатно, локально, хорошее качество |
| TTS | Edge TTS | Основной TTS для MVP. Позже можно заменить на ElevenLabs без изменения архитектуры |
| 3D avatar | Unity + VRM или готовый VTuber tool | Не писать 3D‑движок самому |
| Avatar protocol | WebSocket/HTTP bridge | Backend управляет эмоциями, lipsync, событиями |
| Sandbox | Сначала проектная папка, потом Docker | Безопасно и реалистично |
| Логи | structlog/loguru + DB events | Удобно смотреть в UI |
| Конфиги | .env + Pydantic Settings | Просто и надежно |
| Секреты | .env в MVP, keyring/шифрование позже | Не усложнять старт |

Python хорош для backend API, LLM‑оркестрации, агентов, STT/TTS, работы с файлами, sandbox‑runner, прототипирования и интеграции с Docker.

Python хуже для тяжелого real-time rendering, сложного desktop UI, низкоуровневой системной изоляции и production desktop‑приложения с красивым UX.

Итог:

- core/backend/agents — Python;
- web UI — TypeScript;
- 3D avatar — Unity/C#/VRM или готовая VTuber‑программа;
- низкоуровневая безопасность — Docker/Windows permissions, позже возможно Rust‑компоненты.

---

# 6. Абстракция для LLM‑провайдеров

Код агента не должен знать, используется ли DeepSeek, Mistral, Gemini, OpenAI или локальная модель.

Плохо:

```python
response = openai.chat.completions.create(...)
```

Хорошо:

```python
response = await llm.generate(messages, model="character_default")
```

## Базовый интерфейс

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Any

Role = Literal["system", "user", "assistant", "tool"]

@dataclass
class ChatMessage:
    role: Role
    content: str

@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None

@dataclass
class LLMRequest:
    messages: list[ChatMessage]
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    response_format: str | None = None

class BaseLLMProvider(ABC):
    name: str

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        pass

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        pass
```

## Model registry

```yaml
models:
  character_default:
    provider: mistral
    model: mistral-small-latest
    temperature: 0.9

  character_funny:
    provider: deepseek
    model: deepseek-chat
    temperature: 1.0

  dev_default:
    provider: gemini
    model: gemini-code
    temperature: 0.2

  dev_strong:
    provider: anthropic
    model: claude-sonnet
    temperature: 0.1
```

Важно: в коде используется `dev_default`, а не конкретное имя модели. Модельные имена, тарифы, лимиты и availability меняются. Поэтому model id нельзя жестко зашивать в код.

---

# 7. Архитектура персонажа‑ассистента

Character Agent — это не просто чат с LLM. Это слой, который отвечает за:

1. личность;
2. стиль ответа;
3. определение намерения пользователя;
4. маршрутизацию задач;
5. короткие ответы для голоса;
6. команды для эмоций/мимики;
7. память;
8. безопасность общения.

## Внутренний pipeline

```text
Input text
  ↓
Context builder:
  - история диалога
  - текущая личность
  - настройки пользователя
  - активные задачи
  - доступный desktop context
  ↓
Intent classifier:
  - casual_chat
  - coding_task
  - system_question
  - settings_change
  - memory_update
  - screen_analysis
  ↓
Character response generator
  ↓
Action extractor:
  - speak_text
  - emotion
  - avatar_animation
  - create_task
  - ask_confirmation
  ↓
Output to:
  - TTS
  - Avatar
  - Task Queue
  - Web UI
```

## Структурированный ответ персонажа

```json
{
  "visible_reply": "Окей, великий архитектор калькуляторов, сейчас соберем тебе это чудо инженерной мысли.",
  "intent": "coding_task",
  "emotion": "smirk",
  "animation": "tease",
  "should_create_task": true,
  "task": {
    "type": "dev",
    "title": "Create Python calculator",
    "requirements": [
      "CLI calculator",
      "support + - * /",
      "handle division by zero",
      "include README"
    ]
  }
}
```

Ответ нужно валидировать через Pydantic, потому что LLM иногда выдает “почти JSON, мамой клянусь JSON”.

## Personality config

```yaml
personality:
  id: sarcastic_programmer
  display_name: "Саркастичный программист"
  language: "ru/en"
  tone:
    sarcasm: 0.7
    toxicity: 0.25
    helpfulness: 0.95
    profanity: 0.0
  boundaries:
    no_real_insults: true
    no_hate: true
    no_harassment: true
    keep_user_safe: true
  catchphrases:
    - "Ну конечно, опять Python спасает человечество."
    - "Ладно, сейчас сделаем, пока ты не передумал."
```

Важно: делать не токсичного ассистента, а театральный пресет личности. Сарказм направлен на ситуацию, код и баги, а не на реальные личные качества пользователя. Должны быть настройки интенсивности и возможность выключить стиль.

Правильный стиль:

> “Этот код выглядит так, будто его писал сонный енот, но ничего, сейчас приведем его в порядок.”

Плохой стиль:

> “Ты тупой, бросай программирование.”

---

# 8. Архитектура fullstack dev‑агента

Dev Agent добавляется после стабильного Character Agent.

Он должен уметь:

- принимать структурированную задачу;
- читать проект;
- строить план;
- предлагать изменения;
- создавать/редактировать файлы;
- запускать команды;
- тестировать;
- исправлять ошибки;
- показывать diff;
- ждать подтверждения пользователя;
- вести журнал действий.

## Dev Agent pipeline

```text
Task received
  ↓
Analyze requirements
  ↓
Inspect workspace
  ↓
Create plan
  ↓
Ask approval, если действие рискованное
  ↓
Generate patches
  ↓
Show diff
  ↓
Apply patch
  ↓
Run tests/commands
  ↓
Read errors
  ↓
Fix
  ↓
Final report
```

## Tool‑based design

Dev Agent не должен иметь магический доступ. Он вызывает инструменты:

```python
class DevTools:
    async def list_files(self, path: str) -> list[str]: ...
    async def read_file(self, path: str) -> str: ...
    async def write_file(self, path: str, content: str) -> None: ...
    async def apply_patch(self, patch: str) -> None: ...
    async def run_command(self, command: list[str]) -> CommandResult: ...
    async def get_git_diff(self) -> str: ...
    async def run_tests(self) -> TestResult: ...
```

## Уровни подтверждения

| Действие | MVP правило |
|---|---|
| Читать файлы в project folder | Разрешено |
| Создать новый файл | Разрешено или approve |
| Изменить существующий файл | Показывать diff |
| Удалить файл | Только approve |
| Запустить python, pytest, npm test | Разрешено в sandbox |
| Запустить rm/del/format/curl pipe shell | Запрещено |
| Доступ к системным папкам | Запрещено |
| Установка пакетов | Approve |
| Интернет | По умолчанию отключен в sandbox, позже настраиваемо |

На старте Dev Agent можно сделать проще: получает задачу, создает проект в папке, генерирует файлы, запускает тест, показывает результат. Потом добавить diff, patch‑loop, Git integration, browser automation и screen context.

---

# 9. Архитектура Web UI

Web UI лучше делать начиная с v0.2.

Рекомендуемый стек:

```text
React + TypeScript + Vite
TailwindCSS
shadcn/ui или Mantine
WebSocket для live events
REST API для CRUD
```

Next.js для локального инструмента не обязателен. Vite проще.

## Основные страницы

```text
/dashboard
  - активные задачи
  - статус агентов
  - состояние voice/avatar/backend

/chat
  - диалог с персонажем
  - выбор личности
  - выбор модели

/tasks
  - список задач
  - статусы
  - логи
  - ошибки
  - кнопки approve/reject/stop

/agents
  - Character Agent
  - Dev Agent
  - будущие агенты

/settings/providers
  - API keys
  - модели
  - лимиты
  - test connection

/settings/personality
  - пресеты
  - сарказм
  - язык
  - эмоции

/settings/sandbox
  - рабочая папка
  - разрешенные команды
  - Docker on/off
  - approval policy

/logs
  - системные события
  - LLM calls
  - tool calls
  - ошибки
```

## Live events

Backend должен пушить события:

```json
{
  "event_type": "task.status_changed",
  "task_id": "task_123",
  "status": "running",
  "message": "Dev agent is generating files"
}
```

```json
{
  "event_type": "agent.message",
  "agent": "character",
  "content": "Я передал задачу dev-агенту. Он уже страдает вместо тебя."
}
```

```json
{
  "event_type": "sandbox.command_finished",
  "command": "pytest",
  "exit_code": 0,
  "duration_ms": 1250
}
```

---

# 10. Архитектура sandbox и доступа к ПК

В MVP агенту не нужен полный доступ к ПК.

Полный доступ к ПК — это риск удаления файлов, утечки токенов/API‑ключей, запуска вредных команд, чтения личных данных, случайных действий из‑за галлюцинации LLM, prompt injection из файлов/страниц и проблем, если проект станет продуктом.

## Уровни доступа

### Level 0 — No PC access

Только чат. Без файлов и команд. Подходит для v0.1.

### Level 1 — Project folder only

Агент работает только в:

```text
C:/Users/<you>/AI-VTuber/workspaces/project_name/
```

Может читать/писать только там. Подходит для первого Dev Agent.

### Level 2 — Project folder + safe commands

Разрешены команды:

```text
python
pip
pytest
node
npm test
npm install с approve
git diff
git status
```

Запрещены:

```text
rm -rf
del /s
format
powershell Invoke-WebRequest | iex
curl | sh
доступ к AppData, Documents, Desktop без разрешения
```

### Level 3 — Docker sandbox

Команды выполняются внутри контейнера.

Плюсы:

- изоляция;
- легче rollback;
- можно ограничить сеть;
- можно ограничить CPU/RAM;
- безопаснее запускать чужой код.

Минусы:

- на Windows сложнее UX;
- Docker Desktop требует настройки;
- GUI‑приложения тестировать сложнее.

### Level 4 — Screen context

Агент может получать скриншоты, OCR/vision‑описание, активное окно. Для v0.6+.

### Level 5 — Browser automation

Playwright‑браузер в контролируемом профиле. Лучше, чем доступ к личному браузеру.

### Level 6 — Full desktop control

Мышь, клавиатура, окна, программы. Это не MVP. Это “давайте дадим еноту бензопилу”.

## Рекомендуемый MVP‑sandbox

```text
v0.5:
  - project folder only
  - command allowlist
  - diff before changes
  - approval for destructive actions
  - logs
  - snapshots before write
```

Позже:

```text
v0.7/v1.0:
  - Docker sandbox
  - network control
  - per-task workspace
  - automatic rollback
  - resource limits
```

---

# 11. Как подключать STT/TTS

## STT варианты

### Вариант A — faster-whisper локально

Плюсы:

- приватно;
- бесплатно после установки;
- нормально работает на RTX 3080;
- можно начать без облака.

Минусы:

- нагрузка на GPU/CPU;
- задержка;
- нужно подбирать модель.

Рекомендация для MVP: `faster-whisper small/medium`.

### Вариант B — cloud STT

Плюсы: выше качество, меньше нагрузка на ПК, проще для слабых машин.

Минусы: платно, приватность, зависимость от API.

### Вариант C — гибрид

Сделать интерфейс:

```text
BaseSTTProvider
  LocalWhisperSTT
  CloudSTT
```

И выбирать в настройках.

## TTS варианты

### Edge TTS

Плюсы: быстро, дешево/бесплатно, есть русские и английские голоса, хорошо для MVP.

Минусы: не самый “аниме‑VTuber” голос, меньше кастомизации.

### Piper

Плюсы: локально, быстро, приватно.

Минусы: качество зависит от голоса, эмоции ограничены.

### ElevenLabs / похожие сервисы

Плюсы: качество и эмоции, можно делать персонажный голос.

Минусы: платно, API‑лимиты, приватность.

## Voice pipeline

```text
Microphone
  ↓
VAD detects speech
  ↓
Record segment
  ↓
STT
  ↓
Character Agent
  ↓
LLM response
  ↓
TTS generates audio
  ↓
Audio playback
  ↓
Avatar lipsync receives amplitude/phonemes
```

Для MVP:

```text
v0.3:
  - push-to-talk или manual record button
  - faster-whisper или cloud STT
  - Edge TTS
  - audio playback
```

Потом:

```text
v0.4+:
  - VAD
  - interrupt/barge-in
  - streaming STT
  - streaming TTS
  - emotions/lipsync
```

---

# 12. Как подключать 3D/VTuber‑модель

Ты хочешь 3D. Значит есть несколько путей.

## Вариант 1 — Unity + VRM

Рекомендуется для долгосрочного проекта.

Плюсы:

- полноценный 3D;
- VRM‑модели;
- эмоции;
- анимации;
- lipsync;
- можно сделать отдельное desktop‑окно;
- потом можно развивать как продукт.

Минусы:

- нужен C#/Unity;
- сложнее MVP;
- придется делать bridge между Python и Unity.

Архитектура:

```text
Python Backend
  ↓ WebSocket
Unity Avatar App
  ↓
VRM Model
```

Команды:

```json
{
  "type": "speak",
  "text": "Ну что, опять калькулятор?",
  "audio_file": "output.wav",
  "emotion": "smirk",
  "animation": "talk"
}
```

```json
{
  "type": "set_emotion",
  "emotion": "annoyed"
}
```

```json
{
  "type": "trigger_animation",
  "name": "facepalm"
}
```

## Вариант 2 — готовая VTuber‑программа + API

Плюсы: быстрее получить визуал, меньше 3D‑разработки.

Минусы: зависимость от сторонней программы, ограничения кастомизации.

## Вариант 3 — Three.js в браузере

Плюсы: все в Web UI, TypeScript, удобно для демонстраций.

Минусы: 3D‑анимации и lipsync придется делать аккуратно; как desktop‑персонаж хуже, чем Unity.

## Рекомендация

Для MVP:

```text
v0.4:
  Unity + простая VRM модель + WebSocket bridge
```

Пока нет своей модели — использовать временную бесплатную VRM‑модель для разработки. Собственный персонаж можно заказать/сделать позже.

---

# 13. Как реализовать память и личность персонажа

## Уровни памяти

### Short-term memory

Контекст текущего диалога:

```text
последние N сообщений
активные задачи
текущая тема
```

### Long-term memory

Факты о пользователе и предпочтениях:

```text
- пользователь предпочитает русский язык
- пользователь учит Rust
- пользователь хочет саркастичного ассистента
- рабочая папка проектов: ...
```

### Project memory

Память по конкретным проектам:

```text
- стек проекта
- структура файлов
- последние задачи
- известные ошибки
```

### Personality memory

Настройки персонажа:

```text
- стиль
- уровень сарказма
- запрещенные темы
- catchphrases
- голос
- аватар
```

## MVP storage

Сначала SQLite:

```text
messages
tasks
task_events
agent_logs
settings
memories
llm_calls
```

SQLite используется для хранения истории сообщений и настроек приложения. API-ключи и секреты хранятся только в .env. PostgreSQL понадобится, когда появится несколько пользователей, облачная версия, team accounts, тяжелые логи или SaaS.

Embeddings в MVP не нужны. Добавить позже для поиска по истории, памяти проектов, документации и RAG по кодовой базе.

Для v1.0 можно рассмотреть:

```text
SQLite + sqlite-vec
или Qdrant
или Chroma
```

---

# 14. End-to-end сценарий: «сделай калькулятор на Python»

## Шаг 1. Пользователь говорит

```text
"Сделай калькулятор на Python"
```

## Шаг 2. STT

```json
{
  "text": "Сделай калькулятор на Python",
  "language": "ru",
  "confidence": 0.94
}
```

## Шаг 3. Character Agent

Внутри он классифицирует intent:

```json
{
  "intent": "coding_task",
  "confidence": 0.98
}
```

Формирует ответ:

```text
"Окей, калькулятор на Python. Величайшая инженерная задача после запуска ракеты. Передаю dev-агенту."
```

И задачу:

```json
{
  "type": "dev_task",
  "title": "Create Python CLI calculator",
  "requirements": [
    "Create a CLI calculator in Python",
    "Support addition, subtraction, multiplication, division",
    "Handle invalid input",
    "Handle division by zero",
    "Add README",
    "Add basic tests"
  ],
  "workspace": "workspaces/python_calculator",
  "approval_policy": "show_diff_before_apply"
}
```

## Шаг 4. Task Queue

```text
task_id = task_0001
status = queued
```

Web UI показывает:

```text
[queued] Create Python CLI calculator
```

## Шаг 5. Dev Agent планирует

```text
Plan:
1. Create project folder.
2. Create calculator.py.
3. Create tests/test_calculator.py.
4. Create README.md.
5. Run pytest.
6. Fix errors if needed.
```

## Шаг 6. Dev Agent генерирует diff

```diff
+ calculator.py
+ tests/test_calculator.py
+ README.md
```

Web UI показывает diff и кнопку approve.

## Шаг 7. Sandbox применяет изменения

Разрешено, потому что это project folder.

## Шаг 8. Запуск тестов

```text
pytest
```

Результат:

```text
5 passed
```

## Шаг 9. Отчет

Dev Agent:

```json
{
  "status": "completed",
  "files_created": [
    "calculator.py",
    "tests/test_calculator.py",
    "README.md"
  ],
  "tests": "5 passed",
  "summary": "Created a Python CLI calculator with tests and README."
}
```

Character Agent пользователю:

```text
"Готово. Калькулятор создан, тесты прошли. Даже удивительно: на этот раз Python не решил самоуничтожиться."
```

---

# 15. Roadmap MVP по версиям v0.1–v1.0

## v0.1 — минимальный текстовый ассистент + LLM abstraction

Цель: сделать надежный текстовый чат с Character Agent и заменяемыми LLM‑провайдерами.

Функционал:

- FastAPI backend;
- CLI или простой web chat;
- LLM Provider abstraction;
- конфиги моделей;
- Character prompt;
- история сообщений в SQLite;
- логирование LLM calls;
- поддержка хотя бы 1–2 провайдеров: Mistral/DeepSeek/Gemini.

Критерии готовности:

- можно написать сообщение;
- ответ приходит от выбранного провайдера;
- можно поменять модель в конфиге без изменения кода;
- сообщения сохраняются;
- ошибки API логируются.

Риски: API‑ключи/лимиты, нестабильность бесплатных тарифов, разный формат ошибок у провайдеров.

## v0.2 — Web UI для задач, логов и настроек

Цель: сделать локальную панель управления.

Функционал:

- React + TypeScript UI;
- страница чата;
- страница логов;
- страница settings/providers;
- WebSocket события;
- выбор personality/model;
- просмотр LLM ошибок.

Критерии готовности:

- UI работает на localhost;
- можно общаться с агентом;
- видны логи;
- можно выбрать модель;
- есть live status backend connection.

Риски: слишком рано добавить много UI; настройки API‑ключей могут быть небезопасны.

## v0.3 — голосовое общение STT/TTS

Цель: добавить голосовой цикл.

Функционал:

- запись микрофона;
- push-to-talk;
- STT provider interface;
- TTS provider interface;
- audio playback;
- русский/английский язык;
- настройка голоса.

Критерии готовности:

- пользователь говорит;
- текст корректно распознается;
- ответ генерируется;
- ответ озвучивается.

Риски: задержка, ошибки распознавания, сложность interruption/barge-in.

Пока не делать:

- постоянное прослушивание;
- эмоциональный voice cloning;
- идеальный real-time lip sync.

## v0.4 — 3D/VTuber avatar

Цель: добавить визуального персонажа.

Функционал:

- Unity/VRM avatar app;
- WebSocket bridge backend ↔ avatar;
- базовые эмоции: neutral, happy, annoyed, smug, thinking;
- lipsync по audio amplitude;
- trigger animations.

Критерии готовности:

- модель отображается;
- при ответе двигает губами;
- меняет эмоции по команде backend;
- есть idle animation.

Риски: Unity займет много времени, нет своей модели, lipsync может выглядеть криво.

Временное решение: использовать placeholder VRM‑модель.

## v0.5 — Dev Agent + sandbox project folder

Цель: добавить первого dev‑агента без полного доступа к ПК.

Функционал:

- Dev task queue;
- Project workspace;
- File tools;
- Command tools;
- Allowlist команд;
- Diff preview;
- Approval перед изменениями;
- Basic tests runner;
- логи действий.

Критерии готовности:

- Character Agent может создать dev task;
- Dev Agent создает простой проект;
- показывает diff;
- запускает тесты;
- возвращает отчет.

Риски: LLM будет ломать код, команды могут зависнуть, нужно ограничивать filesystem.

## v0.6 — визуальный контекст экрана/рабочего стола

Цель: дать ассистенту ограниченное понимание экрана.

Функционал:

- screenshot capture по запросу;
- active window title;
- OCR/vision analysis через модель;
- пользователь подтверждает отправку скриншота в API;
- screen context в prompt.

Критерии готовности:

- пользователь говорит: “что у меня на экране?”;
- ассистент делает скриншот с подтверждением;
- возвращает описание;
- скриншоты логируются/удаляются по политике.

Риски: приватность, утечка паролей/API‑ключей, prompt injection с экрана.

## v1.0 — стабильная мультиагентная система

Цель: собрать платформу, которую можно показывать, развивать и потенциально превращать в продукт.

Функционал:

- Character Agent;
- Voice pipeline;
- 3D avatar;
- Web UI;
- Dev Agent;
- Sandbox;
- Plugin system для новых агентов;
- Memory;
- Settings;
- Logs;
- Provider switching;
- Export/import config;
- Safe mode;
- документация.

Критерии готовности:

- система стабильно работает часами;
- ошибки не роняют весь backend;
- можно менять провайдера;
- можно добавлять агента через plugin interface;
- есть ограничения доступа;
- есть понятные логи.

---

# 16. Пример структуры репозитория

```text
neuro-vtuber-assistant/
  README.md
  .env.example
  docker-compose.yml
  pyproject.toml

  apps/
    backend/
      main.py
      app/
        core/
          config.py
          logging.py
          events.py
          errors.py

        api/
          routes/
            chat.py
            tasks.py
            agents.py
            settings.py
            logs.py
            voice.py
          websocket.py

        llm/
          base.py
          registry.py
          messages.py
          providers/
            mistral.py
            deepseek.py
            gemini.py
            openai.py
            anthropic.py
            ollama.py

        agents/
          base.py
          character/
            agent.py
            prompts.py
            personality.py
            intent.py
            schemas.py
          dev/
            agent.py
            planner.py
            tools.py
            patcher.py
            schemas.py

        tasks/
          models.py
          queue.py
          runner.py
          service.py

        voice/
          stt/
            base.py
            faster_whisper.py
          tts/
            base.py
            edge_tts.py
            piper.py
          audio.py
          vad.py

        avatar/
          base.py
          bridge.py
          unity.py
          vtube_studio.py
          emotion.py

        sandbox/
          base.py
          local.py
          docker.py
          policies.py
          approvals.py
          snapshots.py

        storage/
          db.py
          models.py
          repositories/
            messages.py
            tasks.py
            settings.py
            memory.py
            logs.py

        memory/
          short_term.py
          long_term.py
          summarizer.py

        prompts/
          character_default.md
          character_sarcastic.md
          dev_agent.md
          router.md

        tests/
          test_llm_registry.py
          test_character_agent.py
          test_task_queue.py
          test_sandbox_policy.py

    web/
      package.json
      index.html
      src/
        main.tsx
        api/
          client.ts
          websocket.ts
        pages/
          ChatPage.tsx
          DashboardPage.tsx
          TasksPage.tsx
          SettingsPage.tsx
          LogsPage.tsx
        components/
          ChatWindow.tsx
          TaskList.tsx
          AgentStatus.tsx
          ProviderSettings.tsx

    avatar-unity/
      README.md

  workspaces/
    .gitkeep

  docs/
    architecture.md
    roadmap.md
    security.md
    api.md
```

---

# 17. Пример базовых интерфейсов/классов на Python

## LLM registry

```python
from dataclasses import dataclass

@dataclass
class ModelConfig:
    alias: str
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None

class LLMRegistry:
    def __init__(self):
        self.providers = {}
        self.models = {}

    def register_provider(self, provider):
        self.providers[provider.name] = provider

    def register_model(self, config: ModelConfig):
        self.models[config.alias] = config

    async def generate(self, alias: str, messages: list):
        config = self.models[alias]
        provider = self.providers[config.provider]

        request = LLMRequest(
            messages=messages,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )

        return await provider.generate(request)
```

## Character Agent

```python
class CharacterAgent:
    def __init__(
        self,
        llm_registry: LLMRegistry,
        memory,
        task_service,
        personality_service,
    ):
        self.llm = llm_registry
        self.memory = memory
        self.task_service = task_service
        self.personality_service = personality_service

    async def handle_user_message(self, user_text: str, session_id: str):
        personality = await self.personality_service.get_current()
        context = await self.memory.build_context(session_id)

        messages = [
            ChatMessage(role="system", content=personality.system_prompt),
            *context,
            ChatMessage(role="user", content=user_text),
        ]

        response = await self.llm.generate(
            alias=personality.model_alias,
            messages=messages,
        )

        parsed = self.parse_character_response(response.content)

        if parsed.should_create_task:
            await self.task_service.create_task(parsed.task)

        await self.memory.save_message(session_id, "user", user_text)
        await self.memory.save_message(session_id, "assistant", parsed.visible_reply)

        return parsed
```

## Task model

```python
from enum import Enum
from pydantic import BaseModel

class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class AgentTask(BaseModel):
    id: str
    type: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.queued
    payload: dict
```

## Sandbox command policy

```python
class CommandPolicy:
    def __init__(self, allowed_commands: set[str], blocked_patterns: list[str]):
        self.allowed_commands = allowed_commands
        self.blocked_patterns = blocked_patterns

    def validate(self, command: list[str]) -> None:
        if not command:
            raise ValueError("Empty command")

        executable = command[0]

        if executable not in self.allowed_commands:
            raise PermissionError(f"Command not allowed: {executable}")

        joined = " ".join(command).lower()

        for pattern in self.blocked_patterns:
            if pattern in joined:
                raise PermissionError(f"Blocked command pattern: {pattern}")
```

## Dev Agent skeleton

```python
class DevAgent:
    def __init__(self, llm_registry, sandbox, event_bus):
        self.llm = llm_registry
        self.sandbox = sandbox
        self.event_bus = event_bus

    async def run_task(self, task: AgentTask):
        await self.event_bus.emit("task.started", task.model_dump())

        plan = await self.create_plan(task)
        await self.event_bus.emit("dev.plan_created", {"task_id": task.id, "plan": plan})

        patch = await self.generate_patch(task, plan)
        diff = await self.sandbox.preview_patch(patch)

        await self.event_bus.emit("dev.diff_ready", {
            "task_id": task.id,
            "diff": diff,
        })

        await self.sandbox.apply_patch(patch)

        test_result = await self.sandbox.run_command(["pytest"])

        if test_result.exit_code != 0:
            await self.fix_errors(task, test_result)

        await self.event_bus.emit("task.completed", {"task_id": task.id})
```

---

# 18. Список библиотек и фреймворков, которые стоит рассмотреть

## Backend

```text
FastAPI
Uvicorn
Pydantic
SQLAlchemy
Alembic
httpx
websockets
structlog или loguru
python-dotenv
```

## LLM

```text
Official SDKs провайдеров
LiteLLM — optional abstraction
OpenAI Agents SDK — можно изучить, но не обязательно брать сразу
LangGraph — позже, если понадобится сложный state machine
```

Сначала лучше сделать минимальную собственную абстракцию, чтобы не зависеть от чужой агентной модели слишком рано.

## STT

```text
faster-whisper
openai-whisper
SpeechRecognition — только для простых тестов
cloud STT provider later
```

## TTS

```text
edge-tts
piper
ElevenLabs SDK
Coqui TTS, если будет удобно
```

## Audio

```text
sounddevice
pyaudio
webrtcvad
numpy
```

## Web UI

```text
React
TypeScript
Vite
TailwindCSS
shadcn/ui или Mantine
Zustand
TanStack Query
```

## Avatar

```text
Unity
UniVRM
VRM models
WebSocketSharp / NativeWebSocket for Unity
VTube Studio API, если уйдете в Live2D/VTS
```

## Sandbox

```text
Docker SDK for Python
subprocess with strict policy
GitPython
unidiff / difflib
pathspec
```

## Testing

```text
pytest
pytest-asyncio
ruff
mypy
pre-commit
```

---

# 19. Главные риски и как их снизить

## Риск 1. Слишком большой scope

Проект включает VTuber, voice assistant, multi-agent IDE, desktop automation, sandbox и web platform. Это большой продукт.

Как снизить: не начинать с dev‑агента и sandbox. Первый настоящий milestone:

```text
голос → LLM → голос → avatar reaction
```

Пока это не работает стабильно, dev‑агент добавлять рано.

## Риск 2. Нестабильные бесплатные API

Бесплатные/дешевые модели могут иметь лимиты, очереди, слабое качество кода, нестабильный latency и изменение model names.

Как снизить:

```text
LLM Provider Layer
Model aliases
Fallback models
Error handling
Rate limit handling
```

## Риск 3. Задержка голосового ответа

Плохой UX:

```text
сказал фразу → 8 секунд тишины → ответ
```

Как снизить:

```text
VAD
streaming LLM
sentence-by-sentence TTS
partial avatar reactions
```

## Риск 4. 3D‑модель съест слишком много времени

Можно месяцами делать красивого персонажа и не иметь рабочего ассистента.

Как снизить: использовать placeholder avatar. Важнее protocol:

```text
set_emotion
speak
trigger_animation
set_idle_state
```

Модель можно заменить позже.

## Риск 5. Dev‑агент опасен для ПК

LLM может ошибаться, запускать неправильные команды, менять не те файлы.

Как снизить в MVP:

```text
project folder only
diff before write
command allowlist
no full PC access
logs
snapshots
```

## Риск 6. Личность ломает полезность

Если персонаж слишком много “угарает”, он станет раздражающим.

Как снизить — параметры:

```text
sarcasm_level
response_length
humor_frequency
dev_mode_seriousness
```

Режимы:

```text
casual mode: больше юмора
dev mode: коротко, полезно, шутка в начале/конце
debug mode: минимум характера, максимум точности
```

## Риск 7. Ранняя переинженерия

Kubernetes, микросервисы, сложные очереди, distributed tracing — не сейчас.

Как снизить:

```text
FastAPI
SQLite
asyncio.Queue
local WebSocket
.env config
```

Потом заменить части:

```text
SQLite → Postgres
asyncio.Queue → Redis/Celery
local sandbox → Docker sandbox
local UI → desktop wrapper/cloud
```

---

# 20. Что делать первым шагом после прочтения ответа

Первый шаг — создать v0.1 skeleton, не трогая пока 3D, STT, TTS и dev‑агента.

## Конкретная задача №1

Сделать репозиторий:

```text
neuro-vtuber-assistant/
  apps/backend
  apps/web
  docs
```

И реализовать:

```text
FastAPI backend
POST /chat
LLM Provider interface
MistralProvider или DeepSeekProvider
CharacterAgent
SQLite message history
.env config
```

## Минимальный v0.1 endpoint

```http
POST /chat
```

Request:

```json
{
  "session_id": "default",
  "message": "Привет, кто ты?"
}
```

Response:

```json
{
  "reply": "Я твой будущий нейро‑VTuber ассистент. Пока без тела, зато уже с завышенным самомнением.",
  "emotion": "smirk",
  "intent": "casual_chat"
}
```

Почему именно так:

- проверяется backend;
- проверяется LLM API;
- проверяется personality prompt;
- можно получить структурированный ответ;
- можно сохранить историю;
- потом можно подключить TTS/avatar.

---

# Итоговая рекомендация

Лучший путь:

```text
v0.1 — текстовый Character Agent + LLM abstraction
v0.2 — локальный Web UI
v0.3 — STT/TTS
v0.4 — 3D avatar bridge
v0.5 — Dev Agent в project-folder sandbox
v0.6 — screen context
v1.0 — plugin-based multi-agent platform
```

Что не делать в первой версии:

- полный доступ к ПК;
- управление мышью и клавиатурой;
- идеальный Codex‑аналог;
- собственный 3D‑движок;
- Kubernetes;
- сложную микросервисную архитектуру;
- платную кастомную модель персонажа;
- постоянное прослушивание микрофона;
- хранение секретов в базе без понимания security model.

Что писать самому:

- LLM provider abstraction;
- Character Agent;
- task/event system;
- sandbox policies;
- personality config;
- web UI под свои сценарии;
- avatar bridge protocol.

Что брать готовым:

- STT;
- TTS;
- 3D rendering;
- VRM avatar runtime;
- database ORM;
- WebSocket;
- Docker isolation;
- UI components.

Главная инженерная идея: **сначала построить “нервную систему” ассистента, потом прикручивать тело, голос, память и руки для программирования**. Голос и аватар без хорошей архитектуры будут демкой. Хорошая архитектура без аватара — уже продуктовый фундамент.

---

# Как использовать этот файл в новом чате

Можно отправить в новый чат этот файл и написать:

```text
Изучи приложенный blueprint проекта Neuro‑VTuber Assistant. Продолжи с разработки v0.1: помоги создать структуру репозитория, FastAPI backend, LLM provider abstraction, CharacterAgent, SQLite storage и /chat endpoint. Начни с пошагового плана и затем дай код файлов.
```



---

# 21. Architecture Decision Record (ADR)

## ADR-001 — Основная LLM

- Основная модель MVP: **DeepSeek V4 Flash**
- Используется через API.
- Архитектура остается provider-agnostic.
- На разработку закладывается стартовый бюджет:
  - 10M input tokens
  - 10M output tokens

## ADR-002 — Локальные LLM

Для MVP локальные модели не используются.
Причины:
- не занимать RTX 3080;
- быстрее начать разработку;
- GPU остается доступной для Unity и STT.

## ADR-003 — STT

Основной STT:
- faster-whisper.

## ADR-004 — TTS

Основной TTS:
- Edge TTS.

## ADR-005 — Голосовой режим

Для v0.1–v0.3 используется Push-To-Talk.

Pipeline:

User
→ Push-To-Talk
→ faster-whisper
→ DeepSeek V4 Flash
→ Edge TTS
→ Unity Avatar

Streaming STT/LLM/TTS переносится на более поздние версии.

## ADR-006 — Хранение данных

.env:
- API Keys;
- секреты.

SQLite:
- история сообщений;
- настройки приложения;
- память (в будущем).

## ADR-007 — Память

В v0.1 используется только история сообщений.

Без:
- embeddings;
- vector DB;
- RAG;
- долгосрочной памяти.

## ADR-008 — Backend ↔ Unity

Основной транспорт:
- WebSocket.

Через него передаются:
- текст;
- эмоции;
- анимации;
- события;
- состояние агента.

## ADR-009 — Отложенные решения

До завершения рабочего MVP откладываются:
- личность персонажа;
- имя персонажа;
- дизайн персонажа;
- собственная VRM-модель;
- долговременная память;
- Dev Agent;
- Sandbox.
