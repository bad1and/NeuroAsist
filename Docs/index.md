<div align="left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../apps/web/public/brand/iris-wordmark-dark.svg">
    <img src="../apps/web/public/brand/iris-wordmark-light.svg" width="172" alt="Iris">
  </picture>
</div>

# Документация Iris

Iris — голосовой AI-персонаж для Windows. Здесь описаны устройство приложения,
работа с данными и путь от исходников до проверенной сборки.

**Версия исходников — [1.0.0](../VERSION).** Готовность к публикации определяется
[проверками релиза](release-checklist.md), а не номером версии. Открытые условия
собраны в [статусе проекта](MILESTONES.md).

---

## С чего начать

- **Первый запуск:** [руководство пользователя](user-guide.md) и [конфиденциальность](../PRIVACY.md).
- **Запуск из исходников:** [системные требования](system-requirements.md), [окружение](dependencies.md) и [эксплуатация](operations.md).
- **Разработка:** [правила участия](../CONTRIBUTING.md) и [архитектура](architecture.md).
- **Выпуск:** [проверки](release-checklist.md), [порядок выпуска](release-runbook.md) и [карточка сборки](release-evidence.md).
- **Разбор проблемы:** [диагностика](operations.md#диагностика) и [API](api.md).

## Устройство Iris

- [Архитектура](architecture.md) — процессы, владельцы состояния и границы отказов.
- [Голосовой разговор](live-conversation.md) — микрофон, конец реплики и перебивание.
- [Характер Ирис](character-voice.md) — юмор, регистры речи, промпты и расход токенов.
- [Память](chroma-memory.md) — факты, исправления, удаление и поиск.
- [Поиск и новости](awareness.md) — источники и проверка ответа.
- [Навыки в разговоре](conversation-skills.md) — выбор инструментов самой Ирис и добавление новых возможностей.
- [Разработка навыков](skill-development.md) — контракт, пример локального инструмента, регистрация и проверки.
- [Coding Agent](coding-agent.md) — задачи в Docker и применение изменений.
- [HTTP и WebSocket API](api.md) — авторизация и версии протоколов.
- [Три этапа развития](feature-implementation-plan.md) — реализованный объём функций и границы проверки.

[Оболочка Windows](../apps/desktop/README.md) ·
[Unity-аватар](../apps/avatar-unity/README.md) ·
[Движения и поведение аватара](avatar-behavior.md) ·
[Дизайн-система](../design.md) ·
[Правила для агентов](../AGENTS.md)

## Выпуск и сопровождение

- [Приёмка приложения перед установщиком](preinstaller-readiness.md)
- [Второй этап подготовки](release-stage-2-plan.md), [результат](release-stage-2-result.md), [разбор зависимостей](security-dependencies-2026-10-20.md)
  и [карточка следующего кандидата](release-candidate-next.md)
- [Запуск, сборка и диагностика](operations.md)
- [Python-зависимости](dependencies.md) и [правила версий](versioning.md)
- [Условия публикации](release-checklist.md) и [порядок выпуска](release-runbook.md)
- [История изменений](../CHANGELOG.md)
- [Безопасность](../SECURITY.md), [конфиденциальность](../PRIVACY.md) и [сторонние материалы](../THIRD_PARTY_ASSETS.md)

## Измерения и история

[Задержка голосового ответа](voice-latency.md) и [сравнение STT](stt-comparison.md)
содержат датированные измерения. Они помогают воспроизвести методику и не
обещают ту же скорость на другом компьютере.

[Эксперимент Qwen3-TTS](qwen-tts-quality-gate.md) и
[старые планы](archive/README.md) сохранены как история. Их команды и решения
не задают текущую конфигурацию Iris. Краткий старый отчёт
[Live Voice](milestone-9-live-voice.md) ведёт к действующему описанию.

---

<sub>Содержание и оформление: [правила документации](documentation.md).
README доступен на русском и английском; документы подсистем пока на русском.</sub>
