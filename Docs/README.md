# Документация Iris 1.0

Этот каталог разделяет действующие эксплуатационные документы, подробные
описания подсистем и исторические планы. Документы из `archive/` не являются
инструкциями для текущей реализации.

## Основные документы

- [Архитектура](architecture.md) — владельцы процессов, данные и основные потоки.
- [Эксплуатация и сборка](operations.md) — development, диагностика, smoke и release build.
- [Release checklist 1.0](release-checklist.md) — обязательные условия публикации.
- [Release runbook](release-runbook.md) — CI, Windows candidate artifact и ручные evidence gates.
- [Версии](versioning.md) — источник версии, зеркала и порядок подготовки релиза.
- [HTTP и WebSocket API](api.md) — authentication, route groups и transport versions.
- [Текущий статус](MILESTONES.md) — что уже реализовано и что остаётся до публичной версии.
- [Coding Agent](coding-agent.md) — Docker sandbox и границы безопасности.
- [Live conversation](live-conversation.md) — PCM/VAD/Smart Turn/voice lifecycle.
- [Memory и semantic retrieval](chroma-memory.md) — каноническая память и перестраиваемый индекс.
- [Дизайн-система](../design.md) — визуальные токены и правила интерфейса.
- [Desktop shell](../apps/desktop/README.md) и [Unity avatar](../apps/avatar-unity/README.md).

## Специализированные материалы

- [Live Voice milestone report](milestone-9-live-voice.md) — подробности barge-in и latency gate.
- [Qwen3-TTS quality pack](qwen-tts-quality-gate.md) — изолированный исторический эксперимент, не production provider.
- [Third-party assets](../THIRD_PARTY_ASSETS.md) — происхождение и ограничения сторонних ассетов.
- [Privacy](../PRIVACY.md), [Security](../SECURITY.md), [Changelog](../CHANGELOG.md) и [Contributing](../CONTRIBUTING.md).
- `version-manifest-v0.4.1.json` — неизменяемый исторический baseline миграций.

## История

Старые blueprints и branch-specific задания перенесены в [archive/](archive/README.md).
Упоминания V0.4–V0.9 внутри архива описывают соответствующий момент истории и
не должны синхронизироваться с текущей версией продукта.

## Автоматическая проверка

Из корня репозитория:

```powershell
.\.venv\Scripts\python.exe scripts/check_docs.py
```

Проверка требует совпадения version metadata и существования всех локальных
Markdown-ссылок в поддерживаемой документации.
