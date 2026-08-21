# HTTP и WebSocket contracts

FastAPI OpenAPI на запущенном development backend доступен по `/docs` и
`/openapi.json`; он является источником точных request/response schemas. Этот
документ фиксирует transport/lifecycle contracts, которые важны для клиентов.

## Адрес и authentication

Browser development использует `http://127.0.0.1:8000` по умолчанию. Desktop
shell каждый запуск выбирает случайный loopback port и session token.

- HTTP desktop requests передают `X-NeuroAsist-Token`.
- WebSocket desktop connections передают тот же token в query parameter `token`.
- Без token desktop core возвращает `401` или закрывает WebSocket.
- CORS допускает только настроенные local origins.

Не сохраняйте ephemeral token и не включайте его в логи/bug reports.

## Основные HTTP groups

| Group | Назначение |
| --- | --- |
| `/health`, `/readiness`, `/status` | Liveness, readiness по подсистемам и версия приложения |
| `/chat`, `/chat/live` | Typed character reply и unified live response orchestration |
| `/conversation/*` | Active session, character state, reflections и debug |
| `/timeline/*`, `/episodes/*` | Messages, journal, search и episode lifecycle |
| `/memory/*` | Memory CRUD, topics, commitments, audit, retrieval/index diagnostics |
| `/settings/*`, `/models/*` | Runtime preferences, dictionaries and managed models |
| `/voice/*`, `/avatar/*` | Interrupt/audio/TTS status и avatar commands/status |
| `/coding/*` | Isolated Coding Agent tasks and review/apply lifecycle |
| `/events`, `/diagnostics`, `/backups` | Runtime observability and maintenance |
| `/debug/llm/usage` | Content-free token/cache/retry/latency telemetry |

`/voice/chat` не поддерживается и намеренно возвращает `404`; voice input идёт
через WebSocket v3, а ответ использует общий chat/live orchestration.

## WebSockets

### `/ws/events`

Поток runtime events для UI. Desktop query token обязателен. Payload содержит
event identity/type/level/message/metadata; sensitive prompts и chain-of-thought
не являются частью contract.

### `/ws/voice-input/{session_id}?version=3`

Единственный input protocol Live Conversation. После connect клиент отправляет
`voice.input.start`, затем binary PCM16 frames, в конце `voice.input.stop`.
Точный start payload и graceful/disconnect semantics описаны в
[live-conversation.md](live-conversation.md).

Version 1/2 и legacy `mode` отклоняются. Reconnect создаёт нового connection
owner и инвалидирует старые async completions.

### `/ws/voice/{session_id}?version=1`

Response audio/control channel. Version отличается от input protocol намеренно;
эти версии нельзя синхронизировать с application version.

### `/ws/avatar?version=2`

Unity renderer registers supported protocol versions, получает speak/emotion/
gesture/overlay commands и подтверждает playback. Unsupported versions закрываются
policy error. Avatar protocol schemas находятся в `apps/backend/app/avatar` и
`apps/protocol`.

## Compatibility rules

- Application `1.0.0` не меняет номера transport protocols автоматически.
- Client должен использовать OpenAPI/generated schemas, а не угадывать поля.
- Unknown protocol version отклоняется явно.
- `session_id`, `generation`, `turn_id` и `utterance_id` сохраняют ownership;
  late event старой generation игнорируется.
- Durable message/state записывается до публикации dependent events там, где
  recovery требует такого порядка.
