# Chatterbox Multilingual V3 — отдельный эксперимент

Это самостоятельный тестовый стенд. Он не подключается к `apps/backend` и не меняет основной TTS-провайдер.

После запуска откройте `output/listen.html`: там аудиоплееры, одинаковые фразы в разных профилях и задержки генерации. Итоговая таблица находится в `output/RESULTS.md`, сырые данные — в `output/metrics.json`.

Дополнительный quality-pack запускается так:

```powershell
tests/chatterbox_v3_experiment/.venv/Scripts/python.exe tests/chatterbox_v3_experiment/run_quality_tuning.py
```

Его плеер находится в `output/quality-tuning/listen.html`, выводы — в `output/quality-tuning/QUALITY.md`.

Проверка русских ударений запускается отдельно:

```powershell
tests/chatterbox_v3_experiment/.venv/Scripts/python.exe tests/chatterbox_v3_experiment/run_stress_tuning.py
```

Плеер stress-проверки находится в `output/stress-tuning/listen.html`. Для неё в изолированном окружении
должен быть установлен `russian-text-stresser` и совместимый spaCy; в основной проект эта зависимость не добавлялась.

Запуск из корня репозитория (CUDA-окружение стенда уже создано отдельно):

```powershell
tests/chatterbox_v3_experiment/.venv/Scripts/python.exe tests/chatterbox_v3_experiment/run_experiment.py
```

Для быстрой проверки только одной реплики используйте `--quick`.

Параметры по умолчанию:

- baseline: `exaggeration=0.5`, `cfg_weight=0.5`;
- calm: `0.3 / 0.7`, ниже температура и ограничен sampling;
- expressive: `0.7 / 0.3`;
- stable: baseline с более консервативным sampling.

В отчёте `synthesis_ms` — wall-clock задержка до готового WAV, а `RTF` — отношение времени генерации к длительности записи. Модель Multilingual V3 в этом API генерирует целый WAV и не отдаёт первый аудиофрагмент потоково; для оценки «первого звука» есть отдельный `chunked_long_form`.
