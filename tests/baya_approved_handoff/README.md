# Baya — handoff package

Это аккуратно зафиксированный handoff последней Baya-реализации из текущего рабочего дерева. Пакет подготовлен для последующей вставки в проект; production-код этим шагом не изменялся.

## Что зафиксировано

- Silero `v5_5_ru`, speaker `baya`.
- Русские ударения включены; локальный Silero Stress используется как улучшение, а при его недоступности остаётся встроенное ударение модели.
- CPU-режим, 48 кГц, warm-up включён.
- Постобработка: high-pass 60 Гц, мягкий low-pass 12 кГц, DC/edge-fade/peak safety.
- Естественная адаптивная просодия включена.
- Для отдельных предложений можно задавать pitch-preserving скорость `0.70–1.30`; она имеет приоритет над `pace`.
- Для контекстно-зависимых слов сохранён pronunciation override до автоматического stress-слоя.

Одобренным основным профилем считается `normal + natural + tempo 1.0 + adaptive_prosody=true`. Варианты `calm` и `lively` оставлены только как опциональные режимы, а не как новые голоса.

## Где лежит точная реализация

Изменения, которые нужно будет переносить при интеграции, находятся в текущем diff относительно базового коммита и перечислены в `IMPLEMENTATION_MANIFEST.json`. Основные файлы:

- `apps/backend/app/voice/providers.py`
- `apps/backend/app/voice/stress.py`
- `apps/backend/app/voice/service.py`
- `apps/backend/app/voice/delivery.py`
- `apps/backend/app/voice/orchestrator.py`
- `apps/backend/app/voice/live.py`
- `apps/backend/app/schemas/character.py`
- `apps/backend/app/core/config.py`
- `apps/backend/app/api/routes/settings.py`
- `apps/backend/app/agents/character/prompts.py`

Проверки для переноса:

- `tests/test_voice_providers.py`
- `tests/test_character_protocol_v3.py`

Полный снимок этих файлов уже лежит внутри пакета в `source/` с теми же относительными путями. Это позволяет позже сравнить или перенести реализацию, даже если рабочее дерево к тому моменту изменится.

## Как вставлять позже

1. Сначала сохранить или закоммитить текущие изменения в рабочем дереве.
2. Перенести изменения из списка файлов выше одним отдельным commit.
3. Добавить переменную `VOICE_TTS_LOWPASS_CUTOFF_HZ=12000` в окружение.
4. Запустить тесты протокола delivery и provider.
5. Проверить Baya на реальном backend: greeting, обычная фраза, числа/даты и контекстные слова `замок`/`мука`.

Ничего из этого handoff-пакета не подключается автоматически и не меняет production при его создании.

## Артефакты прослушивания

Последние Baya-сравнения находятся в `output/tts-model-comparison/`:

- `listen_baya_polished.html` — основной polished pack;
- `listen_baya_stress_corrections.html` — автоматические и контекстные ударения;
- `listen_baya_sentence_pacing.html` — скорость по отдельным предложениям;
- `listen_baya_artifacts.html` — сравнение фильтрации артефактов.
